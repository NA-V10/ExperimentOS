"""Result parsing and integrity checks for experiment output.

Results come from AI-generated code running in a sandbox, so they are parsed
strictly and re-verified: every reported metric must be recomputable from the
per-question records.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from ..execution.runtime.experimentos_sdk.rag import RAGConfig
from ..models.results import ExperimentResults

RESULT_BEGIN = "@@EOS_RESULT_BEGIN"
RESULT_END = "@@EOS_RESULT_END"
EVENT_PREFIX = "@@EOS "


class ResultParseError(Exception):
    pass


def extract_result_block(output: str) -> dict[str, Any]:
    """Extract the JSON result block printed by ``experimentos_sdk.finish()``."""
    start = output.rfind(RESULT_BEGIN)
    end = output.rfind(RESULT_END)
    if start == -1 or end == -1 or end < start:
        raise ResultParseError("no result block found in experiment output")
    body = output[start + len(RESULT_BEGIN) : end].strip()
    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        raise ResultParseError(f"result block is not valid JSON: {e}") from e


def parse_event_line(line: str) -> dict[str, Any] | None:
    if not line.startswith(EVENT_PREFIX):
        return None
    try:
        payload = json.loads(line[len(EVENT_PREFIX):])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def parse_results(raw: dict[str, Any], expected_run_ids: list[str] | None = None,
                  expected_params: dict[str, dict[str, Any]] | None = None) -> ExperimentResults:
    try:
        results = ExperimentResults.model_validate(raw)
    except ValidationError as e:
        raise ResultParseError(f"results do not match schema: {e.error_count()} errors") from e
    verify_results(results, expected_run_ids, expected_params)
    return results


def verify_results(results: ExperimentResults, expected_run_ids: list[str] | None = None,
                   expected_params: dict[str, dict[str, Any]] | None = None) -> None:
    seen = [r.run_id for r in results.runs]
    if len(seen) != len(set(seen)):
        raise ResultParseError("duplicate run_ids in results")
    if expected_run_ids is not None and sorted(seen) != sorted(expected_run_ids):
        missing = sorted(set(expected_run_ids) - set(seen))
        extra = sorted(set(seen) - set(expected_run_ids))
        raise ResultParseError(f"runs do not match plan (missing={missing}, unexpected={extra})")
    for r in results.runs:
        # The run must have used exactly the planned configuration (defaults included), so a
        # mislabelled or altered run can never be reported as evidence for the plan.
        if expected_params is not None and r.run_id in expected_params:
            planned = RAGConfig(**expected_params[r.run_id]).to_dict()
            diff = {k: (planned[k], r.configuration.get(k)) for k in planned if r.configuration.get(k) != planned[k]}
            if diff:
                raise ResultParseError(f"{r.run_id}: executed configuration differs from the plan "
                                       + ", ".join(f"{k} planned={a} ran={b}" for k, (a, b) in diff.items()))
        n = len(r.per_question)
        correct = sum(q.correct for q in r.per_question)
        recall = sum(q.answer_in_context for q in r.per_question)
        if n != r.metrics.n_questions or correct != r.metrics.n_correct:
            raise ResultParseError(f"{r.run_id}: metrics disagree with per-question records")
        if abs(correct / n - r.metrics.accuracy) > 1e-3 or abs(recall / n - r.metrics.retrieval_recall) > 1e-3:
            raise ResultParseError(f"{r.run_id}: accuracy/recall not recomputable from records")
