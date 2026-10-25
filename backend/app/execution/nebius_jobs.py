"""Experiment execution on Nebius AI Cloud — Serverless AI Jobs (PRODUCTION / NEBIUS JOB MODE).

Flow
----
1. The generated code is written to a local file and injected into the job
   container with ``--inject-file LOCAL:CONTAINER`` (max 64 KiB).
2. ``nebius ai job create`` starts an ephemeral CPU job from the runner image
   (docker/runner.Dockerfile: Python + sandbox bootstrap + SDK + dataset; no
   credentials, no network needed), running the same sandbox bootstrap as local mode.
3. ``nebius ai logs <job-id>`` streams the job output; ``@@EOS`` progress events
   are forwarded live to the UI and the ``@@EOS_RESULT_BEGIN/END`` block carries
   the measured results back.
4. ``nebius ai job get-by-name`` is polled until the job reaches a terminal state.

All CLI invocations use argument vectors (never a shell).
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from ..config import Settings
from ..evaluation.metrics import ResultParseError, extract_result_block
from .code_policy import check_code
from .runner import ExecutionOutcome, OnEvent, pump_lines
from .sandbox import LocalSandboxExecutor

CONTAINER_ROOT = "/opt/experimentos"
TERMINAL_OK = ("COMPLETED", "SUCCEEDED", "SUCCESS", "FINISHED", "DONE")
TERMINAL_BAD = ("FAILED", "ERROR", "CANCELLED", "CANCELED", "STOPPED", "TERMINATED")


def _find_state(obj: Any) -> str | None:
    """Find a job state string anywhere in the CLI's JSON output."""
    if isinstance(obj, dict):
        for key in ("state", "phase", "status"):
            v = obj.get(key)
            if isinstance(v, str):
                return v.upper()
        for v in obj.values():
            found = _find_state(v)
            if found:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _find_state(v)
            if found:
                return found
    return None


class NebiusJobExecutor:
    name = "nebius_job"

    def __init__(self, settings: Settings):
        self.settings = settings

    def _cli(self, *args: str, timeout: float = 120) -> subprocess.CompletedProcess:
        exe = shutil.which(self.settings.nebius_cli) or self.settings.nebius_cli
        return subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout,
                              encoding="utf-8", errors="replace")

    def build_create_args(self, job_name: str, local_code: Path, experiment_id: str) -> list[str]:
        s = self.settings
        container_code = f"{CONTAINER_ROOT}/job/experiment.py"
        args = [
            "ai", "job", "create",
            "--name", job_name,
            "--image", s.nebius_job_image,
            "--container-command", "python",
            "--args", " ".join([
                "-I", "-B", f"{CONTAINER_ROOT}/runtime/bootstrap.py",
                "--code", container_code,
                "--workdir", "/tmp/experimentos-out",
                "--dataset", f"{CONTAINER_ROOT}/data/rag_eval.json",
                "--experiment-id", experiment_id,
                "--cpu-seconds", str(s.execution_timeout_seconds),
                "--memory-mb", str(s.execution_memory_mb),
            ]),
            "--inject-file", f"{local_code}:{container_code}",
            "--platform", s.nebius_job_platform,
            "--preset", s.nebius_job_preset,
            "--timeout", s.nebius_job_timeout,
            "--restart-policy", "never",
            "--async",
            "--format", "jsonpath={.resource_id}",
        ]
        if s.nebius_project_id:
            args += ["--parent-id", s.nebius_project_id]
        return args

    async def execute(self, *, experiment_id: str, code: str, attempt: int, on_event: OnEvent) -> ExecutionOutcome:
        ready, why = self.settings.nebius_jobs_ready()
        if not ready:
            if self.settings.nebius_job_fallback_local:
                await on_event({"type": "backend_fallback", "reason": why})
                return await LocalSandboxExecutor(self.settings).execute(
                    experiment_id=experiment_id, code=code, attempt=attempt, on_event=on_event)
            return ExecutionOutcome(ok=False, backend=self.name, error=f"Nebius job execution unavailable: {why}")

        policy = check_code(code)
        if not policy.ok:
            return ExecutionOutcome(ok=False, backend=self.name, error="code rejected by safety policy")
        if len(code.encode()) > 60_000:
            return ExecutionOutcome(ok=False, backend=self.name, error="code exceeds --inject-file 64 KiB limit")

        work = Path(self.settings.work_root) / experiment_id / f"attempt_{attempt}"
        work.mkdir(parents=True, exist_ok=True)
        local_code = work / "experiment.py"
        local_code.write_text(code, encoding="utf-8")
        job_name = re.sub(r"[^a-z0-9-]", "-", f"experimentos-{experiment_id}-a{attempt}".lower())[:60]

        t0 = time.monotonic()
        created = await asyncio.to_thread(self._cli, *self.build_create_args(job_name, local_code, experiment_id))
        if created.returncode != 0:
            return ExecutionOutcome(ok=False, backend=self.name,
                                    error=f"nebius ai job create failed: {(created.stderr or created.stdout)[-400:]}")
        job_id = created.stdout.strip().splitlines()[-1].strip() if created.stdout.strip() else job_name
        await on_event({"type": "job_submitted", "job_id": job_id, "job_name": job_name,
                        "platform": self.settings.nebius_job_platform, "preset": self.settings.nebius_job_preset})

        logs: list[str] = []
        output: list[str] = []
        deadline = t0 + self.settings.execution_timeout_seconds + 600  # allow for cold start
        state = "PENDING"

        while time.monotonic() < deadline:
            got = await asyncio.to_thread(self._cli, "ai", "job", "get-by-name", "--name", job_name,
                                          "--format", "json")
            if got.returncode == 0:
                try:
                    new_state = _find_state(json.loads(got.stdout)) or state
                except json.JSONDecodeError:
                    new_state = state
                if new_state != state:
                    state = new_state
                    await on_event({"type": "job_state", "job_id": job_id, "state": state})
            if state.startswith(("RUNNING", "STARTING")) or state.startswith(TERMINAL_OK + TERMINAL_BAD):
                break
            await asyncio.sleep(5)

        # Stream logs (forwards live progress events while the job runs).
        exe = shutil.which(self.settings.nebius_cli) or self.settings.nebius_cli
        proc = subprocess.Popen([exe, "ai", "logs", job_id], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace")

        def reader():
            assert proc.stdout is not None
            for line in proc.stdout:
                output.append(line)
                yield line

        try:
            await asyncio.wait_for(pump_lines(reader, on_event, logs), timeout=max(30, deadline - time.monotonic()))
        except asyncio.TimeoutError:
            proc.kill()

        # Wait for a terminal state.
        while time.monotonic() < deadline and not state.startswith(TERMINAL_OK + TERMINAL_BAD):
            got = await asyncio.to_thread(self._cli, "ai", "job", "get-by-name", "--name", job_name, "--format", "json")
            if got.returncode == 0:
                try:
                    state = _find_state(json.loads(got.stdout)) or state
                except json.JSONDecodeError:
                    pass
            if not state.startswith(TERMINAL_OK + TERMINAL_BAD):
                await asyncio.sleep(5)
        await on_event({"type": "job_state", "job_id": job_id, "state": state})

        text = "".join(output)
        if "@@EOS_RESULT_END" not in text:  # logs may not have been complete while streaming
            again = await asyncio.to_thread(self._cli, "ai", "logs", job_id, timeout=180)
            text = again.stdout or text

        outcome = ExecutionOutcome(ok=False, backend=self.name, job_id=job_id, logs=logs,
                                   duration_s=round(time.monotonic() - t0, 2),
                                   sandbox=f"Nebius Serverless AI Job · {self.settings.nebius_job_platform} / "
                                           f"{self.settings.nebius_job_preset} · ephemeral container")
        try:
            outcome.raw_results = extract_result_block(text)
        except ResultParseError as e:
            outcome.error = f"job {job_id} ended in state {state}: {e}"
            outcome.timed_out = time.monotonic() >= deadline
            return outcome
        outcome.ok = True
        return outcome
