"""Shared dependencies passed to every agent component."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol

from ..llm.nebius_client import LLMClient


class Emit(Protocol):
    def __call__(self, event_type: str, message: str, **data: Any) -> Awaitable[None]: ...


async def _noop_emit(event_type: str, message: str, **data: Any) -> None:
    return None


@dataclass
class AgentContext:
    llm: LLMClient | None
    emit: Callable[..., Awaitable[None]] = _noop_emit
    max_attempts: int = 3

    @property
    def offline(self) -> bool:
        return self.llm is None
