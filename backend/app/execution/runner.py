"""Execution backends for generated experiments.

* ``local``  — LocalSandboxExecutor: isolated subprocess on this machine
               (LOCAL DEVELOPMENT MODE on Windows: no kernel resource limits).
* ``nebius`` — NebiusJobExecutor: Nebius AI Cloud Serverless AI Job (ephemeral
               container, PRODUCTION / NEBIUS JOB MODE).
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable, Protocol

from ..config import Settings
from ..evaluation.metrics import parse_event_line

OnEvent = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class ExecutionOutcome:
    ok: bool
    backend: str
    raw_results: dict[str, Any] | None = None
    error: str | None = None
    logs: list[str] = field(default_factory=list)
    duration_s: float = 0.0
    job_id: str | None = None
    sandbox: str = ""
    timed_out: bool = False


class Executor(Protocol):
    name: str

    async def execute(self, *, experiment_id: str, code: str, attempt: int, on_event: OnEvent) -> ExecutionOutcome: ...


async def pump_lines(
    reader: Callable[[], Iterable[str]], on_event: OnEvent, logs: list[str], max_log_lines: int = 400
) -> None:
    """Consume lines produced by a blocking iterator (in a thread) and dispatch events."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def worker() -> None:
        try:
            for line in reader():
                loop.call_soon_threadsafe(queue.put_nowait, line)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    threading.Thread(target=worker, daemon=True).start()
    in_result = False
    while (line := await queue.get()) is not None:
        line = line.rstrip("\r\n")
        if line.startswith("@@EOS_RESULT_BEGIN"):
            in_result = True
            continue
        if line.startswith("@@EOS_RESULT_END"):
            in_result = False
            continue
        if in_result:
            continue  # result JSON is read from results.json / the block parser
        event = parse_event_line(line)
        if event is not None:
            await on_event(event)
        elif line.strip():
            logs.append(line[:500])
            if len(logs) > max_log_lines:
                del logs[: len(logs) - max_log_lines]


def get_executor(settings: Settings) -> Executor:
    from .nebius_jobs import NebiusJobExecutor
    from .sandbox import LocalSandboxExecutor

    if settings.execution_mode == "nebius":
        return NebiusJobExecutor(settings)
    return LocalSandboxExecutor(settings)
