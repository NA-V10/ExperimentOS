"""Experiment runtime: dataset access, seeding, progress reporting and result recording.

Generated experiment code talks to the outside world *only* through these
functions. Output protocol (stdout, one JSON object per line):

    @@EOS {"type": "progress", ...}
    @@EOS {"type": "run_complete", ...}
    @@EOS_RESULT_BEGIN
    {...full results JSON...}
    @@EOS_RESULT_END

The result block lets remote executors (Nebius Serverless Jobs) recover results
from job logs; the local runner additionally reads ``results.json`` from the
working directory.
"""

from __future__ import annotations

import json
import random
import sys
from typing import Any

from .rag import RAGConfig, evaluate_rag

_STATE: dict[str, Any] = {
    "experiment_id": "unknown",
    "dataset": None,
    "workdir": None,
    "seed": None,
    "runs": [],
    "total_evaluations": 0,
    "done_evaluations": 0,
    "finished": False,
}

MAX_RUNS = 24


def _emit(payload: dict) -> None:
    sys.stdout.write("@@EOS " + json.dumps(payload) + "\n")
    sys.stdout.flush()


def _configure(experiment_id: str, dataset: dict, workdir: str) -> None:
    """Called by the sandbox bootstrap before user code runs."""
    _STATE.update(experiment_id=experiment_id, dataset=dataset, workdir=workdir)


def set_seed(seed: int = 42) -> None:
    random.seed(seed)
    _STATE["seed"] = seed


def load_dataset() -> dict:
    if _STATE["dataset"] is None:
        raise RuntimeError("dataset not available in this runtime")
    return _STATE["dataset"]


def plan_evaluations(n_runs: int) -> int:
    """Declare how many runs will execute so progress can be reported as done/total."""
    n_q = len(load_dataset()["questions"])
    _STATE["total_evaluations"] = n_runs * n_q
    _emit({"type": "plan", "runs": n_runs, "total": n_runs * n_q})
    return n_runs * n_q


def run_configuration(run_id: str, **params: Any) -> dict:
    """Evaluate one RAG configuration over the full dataset and record it."""
    if len(_STATE["runs"]) >= MAX_RUNS:
        raise RuntimeError(f"too many runs (max {MAX_RUNS})")
    if any(r["run_id"] == run_id for r in _STATE["runs"]):
        raise ValueError(f"duplicate run_id {run_id!r}")
    config = RAGConfig(**params)
    _emit({"type": "run_start", "run_id": run_id, "configuration": config.to_dict()})

    base = _STATE["done_evaluations"]

    def on_progress(done: int, total: int) -> None:
        _STATE["done_evaluations"] = base + done
        if done % 10 == 0 or done == total:
            _emit(
                {
                    "type": "progress",
                    "run_id": run_id,
                    "done": _STATE["done_evaluations"],
                    "total": _STATE["total_evaluations"] or None,
                }
            )

    result = evaluate_rag(load_dataset(), config, on_progress=on_progress)
    record = {"run_id": run_id, **result}
    _STATE["runs"].append(record)
    _emit({"type": "run_complete", "run_id": run_id, "metrics": result["metrics"]})
    return result["metrics"]


def finish() -> dict:
    """Write results.json and print the result block. Must be called exactly once."""
    if _STATE["finished"]:
        raise RuntimeError("finish() already called")
    _STATE["finished"] = True
    dataset = load_dataset()
    results = {
        "experiment_id": _STATE["experiment_id"],
        "seed": _STATE["seed"],
        "dataset_version": dataset.get("version"),
        "runs": _STATE["runs"],
        "metrics": {r["run_id"]: r["metrics"] for r in _STATE["runs"]},
        "artifacts": ["results.json"],
    }
    text = json.dumps(results)
    if _STATE["workdir"]:
        # The bootstrap's audit hook only permits writes inside the working directory.
        with open(_STATE["workdir"] + "/results.json", "w", encoding="utf-8") as fh:
            fh.write(text)
    sys.stdout.write("@@EOS_RESULT_BEGIN\n" + text + "\n@@EOS_RESULT_END\n")
    sys.stdout.flush()
    return results
