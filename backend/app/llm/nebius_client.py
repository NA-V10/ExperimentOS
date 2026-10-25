"""NVIDIA Nemotron via Nebius Token Factory (OpenAI-compatible chat completions API).

Two model tiers, both configured by environment variables (never hard-coded):

* ``fast``      — NEBIUS_FAST_MODEL (falls back to NEBIUS_MODEL): question parsing,
                  research summarisation.
* ``reasoning`` — NEBIUS_MODEL: hypothesis, experiment design, code generation,
                  analysis, next-experiment proposals.

Every call is reported through ``on_call`` so the UI can show exactly which
Nemotron model did what, how long it took and how many tokens it used.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal, Protocol

import httpx

from ..config import Settings
from .usage import LLMBudgetExceeded, UsageTracker

Tier = Literal["fast", "reasoning"]


class LLMError(Exception):
    """Transport/API failure (after retries)."""


class LLMResponseError(LLMError):
    """The model answered, but not with usable output (e.g. invalid JSON)."""


class LLMNotConfigured(LLMError):
    pass


@dataclass
class LLMCall:
    task: str
    tier: Tier
    model: str
    latency_s: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    ok: bool = True
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


CallHook = Callable[[LLMCall], Awaitable[None]]


class LLMClient(Protocol):
    provider: str

    def model_for(self, tier: Tier) -> str: ...

    async def complete_text(
        self, *, task: str, system: str, user: str, tier: Tier = "reasoning",
        temperature: float = 0.2, max_tokens: int = 4096,
    ) -> str: ...

    async def complete_json(
        self, *, task: str, system: str, user: str, tier: Tier = "reasoning",
        temperature: float = 0.1, max_tokens: int = 4096,
    ) -> dict[str, Any]: ...


_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)
_FENCE = re.compile(r"```(?:json|python|py)?\s*\n(.*?)```", re.S | re.I)


def strip_reasoning(text: str) -> str:
    text = _THINK.sub("", text or "")
    # Some reasoning models emit only a closing tag when the opening one is in the template.
    if "</think>" in text:
        text = text.split("</think>", 1)[1]
    return text.strip()


def extract_json(text: str) -> dict[str, Any]:
    """Extract the first JSON object from model output (handles fences and prose)."""
    text = strip_reasoning(text)
    for candidate in [m.group(1) for m in _FENCE.finditer(text)] + [text]:
        candidate = candidate.strip()
        start = candidate.find("{")
        while start != -1:
            depth, in_str, esc = 0, False, False
            for i in range(start, len(candidate)):
                ch = candidate[i]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                elif ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            obj = json.loads(candidate[start : i + 1])
                        except json.JSONDecodeError:
                            break
                        if isinstance(obj, dict):
                            return obj
                        break
            start = candidate.find("{", start + 1)
    raise LLMResponseError("model output did not contain a valid JSON object")


def extract_code(text: str) -> str:
    text = strip_reasoning(text)
    blocks = [m.group(1) for m in _FENCE.finditer(text)]
    if blocks:
        return max(blocks, key=len).strip() + "\n"
    return text.strip() + "\n"


class NebiusClient:
    provider = "nebius-token-factory"

    def __init__(self, settings: Settings, on_call: CallHook | None = None,
                 transport: httpx.AsyncBaseTransport | None = None, usage: UsageTracker | None = None):
        if not settings.nebius_configured:
            raise LLMNotConfigured(settings.configuration_help())
        self.settings = settings
        self.on_call = on_call
        self.usage = usage
        self._live_calls = 0  # per-experiment counter (each experiment gets its own clone)
        self._client = httpx.AsyncClient(
            base_url=settings.nebius_base_url.rstrip("/") + "/",
            headers={"Authorization": f"Bearer {settings.nebius_api_key}"},
            timeout=httpx.Timeout(settings.llm_timeout_seconds, connect=15.0),
            transport=transport,
        )

    def with_hook(self, on_call: CallHook | None) -> "NebiusClient":
        clone = object.__new__(NebiusClient)
        clone.__dict__.update(self.__dict__)
        clone.on_call = on_call
        clone._live_calls = 0
        return clone

    def model_for(self, tier: Tier) -> str:
        return self.settings.fast_model if tier == "fast" else self.settings.reasoning_model

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _chat(self, task: str, system: str, user: str, tier: Tier, temperature: float, max_tokens: int) -> str:
        model = self.model_for(tier)
        body = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        cache_path = self._cache_path(body)
        if cache_path and cache_path.exists():
            try:
                hit = json.loads(cache_path.read_text(encoding="utf-8"))
                await self._report(LLMCall(task=task, tier=tier, model=hit.get("model", model), latency_s=0.0,
                                           extra={"cached": True}))
                return hit["content"]
            except (json.JSONDecodeError, KeyError, OSError):
                pass  # corrupt entry: fall through to a live call
        # Guardrails run BEFORE any request is sent (cache hits above cost nothing and are exempt).
        cap = self.settings.llm_max_calls_per_experiment
        if cap and self._live_calls >= cap:
            raise LLMBudgetExceeded(
                f"This experiment reached its limit of {cap} Nemotron calls (LLM_MAX_CALLS_PER_EXPERIMENT).")
        if self.usage:
            self.usage.check()
        self._live_calls += 1
        last_err: str | None = None
        for attempt in range(self.settings.llm_max_retries + 1):
            t0 = time.perf_counter()
            try:
                resp = await self._client.post("chat/completions", json=body)
                if resp.status_code in (429, 500, 502, 503, 504):
                    last_err = f"HTTP {resp.status_code}"
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                if resp.status_code >= 400:
                    raise LLMError(f"Token Factory returned HTTP {resp.status_code}: {resp.text[:300]}")
                data = resp.json()
                msg = data["choices"][0]["message"]
                content = msg.get("content") or ""
                usage = data.get("usage") or {}
                if self.usage:
                    self.usage.record(int(usage.get("total_tokens")
                                          or (usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0)))
                await self._report(LLMCall(
                    task=task, tier=tier, model=data.get("model", model),
                    latency_s=time.perf_counter() - t0,
                    prompt_tokens=usage.get("prompt_tokens"),
                    completion_tokens=usage.get("completion_tokens"),
                ))
                if not content.strip():
                    raise LLMResponseError("model returned empty content")
                if cache_path:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    cache_path.write_text(json.dumps({"model": data.get("model", model), "content": content}),
                                          encoding="utf-8")
                return content
            except httpx.HTTPError as e:
                last_err = f"{type(e).__name__}: {e}"
                await asyncio.sleep(1.5 * (attempt + 1))
            except (KeyError, IndexError, ValueError) as e:
                if isinstance(e, LLMError):
                    raise
                raise LLMResponseError(f"unexpected response shape: {e}") from e
        await self._report(LLMCall(task=task, tier=tier, model=model, latency_s=0.0, ok=False, error=last_err))
        raise LLMError(f"Token Factory request failed after retries: {last_err}")

    def _cache_path(self, body: dict[str, Any]):
        if not self.settings.llm_cache:
            return None
        key = hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()
        return self.settings.llm_cache_dir / f"{key}.json"

    async def _report(self, call: LLMCall) -> None:
        if self.on_call:
            await self.on_call(call)

    async def complete_text(self, *, task: str, system: str, user: str, tier: Tier = "reasoning",
                            temperature: float = 0.2, max_tokens: int = 4096) -> str:
        return strip_reasoning(await self._chat(task, system, user, tier, temperature, max_tokens))

    async def complete_json(self, *, task: str, system: str, user: str, tier: Tier = "reasoning",
                            temperature: float = 0.1, max_tokens: int = 4096) -> dict[str, Any]:
        system = system + "\n\nRespond with a single JSON object only. No markdown, no commentary."
        return extract_json(await self._chat(task, system, user, tier, temperature, max_tokens))

    async def ping(self) -> dict[str, Any]:
        """Lightweight connectivity check used by /health?deep=true."""
        t0 = time.perf_counter()
        resp = await self._client.get("models")
        return {"ok": resp.status_code == 200, "status_code": resp.status_code,
                "latency_ms": round((time.perf_counter() - t0) * 1000)}
