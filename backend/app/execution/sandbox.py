"""Local sandboxed execution of generated experiment code (subprocess)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from ..config import RUNTIME_DIR, Settings
from ..evaluation.metrics import ResultParseError, extract_result_block
from .code_policy import check_code
from .runner import ExecutionOutcome, OnEvent, pump_lines

BOOTSTRAP = RUNTIME_DIR / "bootstrap.py"


def sandbox_env() -> dict[str, str]:
    """Empty environment: no API keys, no credentials, no PATH."""
    env = {"PYTHONHASHSEED": "0", "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
    if os.name == "nt":  # the Windows CRT needs SYSTEMROOT to initialise
        env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
    return env


class LocalSandboxExecutor:
    name = "local_sandbox"

    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def mode_label(self) -> str:
        return ("LOCAL DEVELOPMENT MODE (Windows: wall-clock timeout + output cap; no kernel resource limits)"
                if os.name == "nt" else "LOCAL SANDBOX (POSIX rlimits: CPU, memory, file size, open files)")

    async def execute(self, *, experiment_id: str, code: str, attempt: int, on_event: OnEvent) -> ExecutionOutcome:
        policy = check_code(code)
        if not policy.ok:  # defence in depth: never run code that fails the static policy
            return ExecutionOutcome(ok=False, backend=self.name, error="code rejected by safety policy: "
                                    + "; ".join(policy.violations or [policy.syntax_error or "missing required calls"]))

        s = self.settings
        root = Path(s.work_root) / experiment_id / f"attempt_{attempt}"
        out_dir = root / "out"
        out_dir.mkdir(parents=True, exist_ok=True)
        code_path = root / "experiment.py"
        code_path.write_text(code, encoding="utf-8")

        cmd = [
            sys.executable, "-I", "-B", str(BOOTSTRAP),
            "--code", str(code_path), "--workdir", str(out_dir), "--dataset", str(s.dataset_path),
            "--experiment-id", experiment_id,
            "--cpu-seconds", str(s.execution_timeout_seconds), "--memory-mb", str(s.execution_memory_mb),
        ]
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        t0 = time.monotonic()
        proc = subprocess.Popen(
            cmd, cwd=out_dir, env=sandbox_env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", creationflags=flags,
        )

        state: dict = {"bytes": 0, "killed": None, "error": None}
        full_output: list[str] = []

        def kill(reason: str) -> None:
            if proc.poll() is None:
                state["killed"] = reason
                proc.kill()

        timer = threading.Timer(s.execution_timeout_seconds, kill, args=("timeout",))
        timer.start()

        def reader():
            assert proc.stdout is not None
            for line in proc.stdout:
                state["bytes"] += len(line)
                if state["bytes"] > s.execution_max_output_bytes:
                    kill("output limit exceeded")
                    break
                full_output.append(line)
                yield line

        async def tap(event: dict) -> None:
            if event.get("type") == "error":
                state["error"] = str(event.get("error", ""))[:500]
            await on_event(event)

        logs: list[str] = []
        try:
            await pump_lines(reader, tap, logs)
        finally:
            timer.cancel()
        rc = proc.wait()
        duration = time.monotonic() - t0
        outcome = ExecutionOutcome(ok=False, backend=self.name, logs=logs, duration_s=round(duration, 2),
                                   sandbox=self.mode_label)

        if state["killed"] == "timeout":
            outcome.timed_out = True
            outcome.error = f"Timeout: exceeded {s.execution_timeout_seconds}s"
            return outcome
        if state["killed"]:
            outcome.error = f"Killed: {state['killed']}"
            return outcome

        results_file = out_dir / "results.json"
        try:
            if results_file.exists():
                outcome.raw_results = json.loads(results_file.read_text(encoding="utf-8"))
            else:
                outcome.raw_results = extract_result_block("".join(full_output))
        except (ResultParseError, json.JSONDecodeError) as e:
            outcome.error = state["error"] or f"exit code {rc}: {e}"
            return outcome
        if rc != 0 or state["error"]:
            outcome.error = state["error"] or f"experiment exited with code {rc}"
            return outcome
        outcome.ok = True
        return outcome
