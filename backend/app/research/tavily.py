"""Optional research discovery with Tavily.

Question -> Tavily web search (runtime) -> Nemotron summarises known findings and the
research gap -> the planner designs an experiment that targets that gap.
If Tavily is not configured or fails, the core loop continues without it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from ..agent import prompts
from ..agent.context import AgentContext
from ..llm.nebius_client import LLMError
from ..models.agent import ResearchContext, ResearchSource

TAVILY_URL = "https://api.tavily.com/search"


class TavilyClient:
    def __init__(self, api_key: str, max_results: int = 5, transport: httpx.AsyncBaseTransport | None = None,
                 cache_dir: Path | None = None):
        self.api_key = api_key
        self.max_results = max_results
        self.transport = transport
        # Reusing results for an identical query saves Tavily credits and keeps the downstream
        # Nemotron prompts identical, so their responses can be replayed from the LLM cache too.
        self.cache_dir = cache_dir
        self.last_cached = False

    def _cache_file(self, query: str) -> Path | None:
        if not self.cache_dir:
            return None
        key = hashlib.sha256(f"{query}|{self.max_results}".encode("utf-8")).hexdigest()
        return self.cache_dir / f"{key}.json"

    async def search(self, query: str) -> list[ResearchSource]:
        cache = self._cache_file(query)
        if cache and cache.exists():
            try:
                self.last_cached = True
                return [ResearchSource(**r) for r in json.loads(cache.read_text(encoding="utf-8"))]
            except (OSError, ValueError, TypeError):
                pass  # corrupt entry: search again
        self.last_cached = False
        sources = await self._search_live(query)
        if cache and sources:
            try:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps([r.model_dump() for r in sources]), encoding="utf-8")
            except OSError:
                pass
        return sources

    async def _search_live(self, query: str) -> list[ResearchSource]:
        async with httpx.AsyncClient(timeout=30.0, transport=self.transport) as client:
            resp = await client.post(
                TAVILY_URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"query": query, "max_results": self.max_results, "search_depth": "basic",
                      "include_answer": False, "topic": "general"},
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
        return [
            ResearchSource(title=r.get("title") or r.get("url", ""), url=r.get("url", ""),
                           snippet=(r.get("content") or "")[:600], score=r.get("score"))
            for r in data.get("results", [])
            if r.get("url")
        ]


def build_query(question: str) -> str:
    return f"{question.strip().rstrip('?')} retrieval-augmented generation evaluation findings"


async def search_research(ctx: AgentContext, tavily: TavilyClient | None, question: str) -> ResearchContext:
    if tavily is None:
        return ResearchContext(searched=False, note="Tavily not configured — skipped existing-evidence search.")
    query = build_query(question)
    try:
        sources = await tavily.search(query)
    except (httpx.HTTPError, ValueError) as e:
        await ctx.emit("warning", f"Tavily search failed ({type(e).__name__}); continuing without prior evidence.",
                       stage="research")
        return ResearchContext(searched=False, query=query, note=f"Tavily search failed: {type(e).__name__}")
    rc = ResearchContext(searched=True, query=query, sources=sources,
                         note="Tavily results reused from cache (no credits used)." if tavily.last_cached else
                              "Live Tavily search.")
    if not sources:
        rc.note = "No sources returned."
        return rc
    if ctx.offline:
        rc.note = "Sources retrieved; summarisation skipped (Nemotron not configured)."
        return rc
    listing = "\n\n".join(f"[{i + 1}] {s.title}\n{s.url}\n{s.snippet}" for i, s in enumerate(sources))
    try:
        raw = await ctx.llm.complete_json(
            task="summarize_research", tier="fast", system=prompts.fmt(prompts.RESEARCH_SYSTEM),
            user=f"Research question: {question}\n\nSearch results:\n{listing}", max_tokens=1536,
        )
        rc.known_findings = [str(x) for x in raw.get("known_findings", [])][:6]
        rc.assumptions = [str(x) for x in raw.get("assumptions", [])][:5]
        rc.research_gap = str(raw.get("research_gap", ""))[:800]
        rc.testable_locally = str(raw.get("testable_locally", ""))[:800]
    except (LLMError, ValidationError, AttributeError) as e:
        await ctx.emit("warning", f"Could not summarise research sources: {e}", stage="research")
    return rc
