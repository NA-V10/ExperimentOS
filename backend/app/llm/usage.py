"""Token-usage guardrails for Nebius Token Factory (protects trial/limited plans).

* Daily token budget (UTC day), persisted to disk so restarts don't reset it.
* Per-experiment call cap, enforced by the per-experiment client clone.

Budget errors are deliberately NOT ``LLMError`` subclasses: agent components retry
on ``LLMError``, but an exhausted budget must stop the experiment immediately.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path


class LLMBudgetExceeded(Exception):
    """The configured token budget or call cap was reached; no request was sent."""


class UsageTracker:
    def __init__(self, path: Path, daily_token_budget: int = 0):
        self.path = path
        self.daily_token_budget = daily_token_budget
        self._lock = threading.Lock()
        self._data = self._load()

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data), encoding="utf-8")
        except OSError:
            pass  # usage tracking must never break an experiment

    def today(self) -> dict[str, int]:
        with self._lock:
            day = self._data.get(self._today(), {})
            return {"tokens": int(day.get("tokens", 0)), "calls": int(day.get("calls", 0))}

    def remaining(self) -> int | None:
        if not self.daily_token_budget:
            return None
        return max(0, self.daily_token_budget - self.today()["tokens"])

    def check(self) -> None:
        remaining = self.remaining()
        if remaining is not None and remaining <= 0:
            raise LLMBudgetExceeded(
                f"Daily Nemotron token budget of {self.daily_token_budget:,} tokens is used up "
                "(LLM_DAILY_TOKEN_BUDGET). It resets at 00:00 UTC; raise the budget in .env to continue."
            )

    def record(self, tokens: int) -> None:
        with self._lock:
            day = self._data.setdefault(self._today(), {"tokens": 0, "calls": 0})
            day["tokens"] = int(day.get("tokens", 0)) + max(0, tokens)
            day["calls"] = int(day.get("calls", 0)) + 1
            # keep the file small: last 30 days only
            for old in sorted(self._data)[:-30]:
                self._data.pop(old, None)
            self._save()
