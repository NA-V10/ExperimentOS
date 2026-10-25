"""Experiment design (``design_experiment``) and deterministic validation (``validate_experiment``)."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from ..execution.runtime.experimentos_sdk.rag import RAGConfig
from ..llm.nebius_client import LLMError
from ..models.agent import ResearchContext
from ..models.experiment import (
    DATASET_ID,
    METRICS,
    PARAMETER_SPACE,
    ExperimentPlan,
    Hypothesis,
    QuestionUnderstanding,
    ValidationCheck,
    ValidationReport,
)
from ..models.results import NextExperimentProposal
from . import offline, prompts
from .context import AgentContext
from .hypothesis import _short


class PlanningError(Exception):
    pass


def _normalise(raw: dict[str, Any]) -> dict[str, Any]:
    """Light, safe normalisation of LLM output before strict validation."""
    raw = dict(raw)
    ds = raw.get("dataset")
    if isinstance(ds, str):
        raw["dataset"] = {"id": ds}
    for c in raw.get("configurations") or []:
        if isinstance(c, dict) and isinstance(c.get("params"), dict):
            c["params"] = {k: (None if v in ("null", "None") else v) for k, v in c["params"].items()}
    raw["metrics"] = [{"name": m} if isinstance(m, str) else m for m in raw.get("metrics") or []]
    raw["independent_variables"] = [
        {"name": v} if isinstance(v, str) else v for v in raw.get("independent_variables") or []
    ]
    raw["control_variables"] = [
        v if isinstance(v, str) else json.dumps(v) for v in raw.get("control_variables") or []
    ]
    return raw


async def design_experiment(
    ctx: AgentContext,
    question: str,
    hypothesis: Hypothesis,
    understanding: QuestionUnderstanding,
    research: ResearchContext | None = None,
    seed_proposal: NextExperimentProposal | None = None,
    revision_feedback: list[str] | None = None,
    previous_plan: ExperimentPlan | None = None,
    max_runs: int = 12,
) -> ExperimentPlan:
    if ctx.offline:
        fam = understanding.experiment_family if understanding.experiment_family in offline.FAMILIES else "retrieval_depth"
        return offline.plan(fam, hypothesis, seed_proposal)

    user = [f"Research question: {question}", f"Hypothesis: {hypothesis.model_dump_json()}"]
    if research and research.searched and research.testable_locally:
        user.append(f"What is testable locally (from prior research): {research.testable_locally}")
    if seed_proposal:
        user.append("Follow-up proposal from the previous experiment's evidence (prefer these configurations):\n"
                    + seed_proposal.model_dump_json(indent=1))
    if revision_feedback and previous_plan:
        user.append("Your previous plan FAILED validation:\n- " + "\n- ".join(revision_feedback)
                    + "\nPrevious plan:\n" + previous_plan.model_dump_json() + "\nReturn a corrected plan.")

    feedback = ""
    for attempt in range(1, ctx.max_attempts + 1):
        try:
            raw = await ctx.llm.complete_json(
                task="design_experiment", tier="reasoning",
                system=prompts.fmt(prompts.PLANNER_SYSTEM, max_runs=max_runs),
                user="\n\n".join(user + ([feedback] if feedback else [])),
                max_tokens=4096,
            )
            return ExperimentPlan.model_validate(_normalise(raw))
        except (ValidationError, LLMError) as e:
            feedback = f"Your previous output did not match the required JSON shape: {_short(e)}"
            await ctx.emit("retry", f"Experiment plan output invalid (attempt {attempt}/{ctx.max_attempts}): {_short(e)}",
                           stage="design")
    raise PlanningError(f"Nemotron could not produce a structurally valid plan after {ctx.max_attempts} attempts.")


def validate_experiment(plan: ExperimentPlan, n_questions: int, max_runs: int = 12,
                        hypothesis: Hypothesis | None = None) -> ValidationReport:
    """Checks 1–7 (code checks 8–9 run after code generation)."""
    configs = plan.configurations
    iv_names = [v.name for v in plan.independent_variables]

    def eff(c, k):  # effective parameter value, including SDK defaults
        return c.params.get(k, PARAMETER_SPACE[k]["default"]) if k in PARAMETER_SPACE else c.params.get(k)

    varied = sorted(k for k in PARAMETER_SPACE if len({repr(eff(c, k)) for c in configs}) > 1)
    unknown_iv = [v for v in iv_names if v not in PARAMETER_SPACE]
    uncontrolled = [k for k in varied if k not in iv_names]
    # rerank_top_n naturally co-varies with reranker; treat as one factor.
    if "reranker" in iv_names:
        uncontrolled = [k for k in uncontrolled if k not in ("rerank_top_n", "retrieval_k")]

    # The plan must test the hypothesis it claims to test.
    off_hypothesis = hypothesis is not None and hypothesis.independent_variable not in varied
    c1_ok = (bool(iv_names) and not unknown_iv and any(v in varied for v in iv_names) and not uncontrolled
             and not off_hypothesis)
    c1 = (f"independent variable(s) {iv_names} vary across runs ({varied})" if c1_ok else
          f"the hypothesis is about '{hypothesis.independent_variable}' but the plan never varies it "
          f"(varied: {varied})" if off_hypothesis else
          "no independent variable" if not iv_names else
          f"unknown parameter(s) {unknown_iv}" if unknown_iv else
          f"uncontrolled parameters vary between runs: {uncontrolled}" if uncontrolled else
          f"independent variable(s) {iv_names} do not actually vary between configurations")

    bad_dv = [d for d in plan.dependent_variables if d not in METRICS]
    c2_ok = bool(plan.dependent_variables) and not bad_dv

    run_ids = [c.run_id for c in configs]
    baselines = [c.run_id for c in configs if c.is_baseline]
    c3_ok = plan.baseline.run_id in run_ids and baselines == [plan.baseline.run_id]

    distinct = len({json.dumps({k: eff(c, k) for k in PARAMETER_SPACE}, sort_keys=True) for c in configs})
    c4_ok = len(configs) >= 2 and len(set(run_ids)) == len(run_ids) and distinct == len(configs)

    c5_ok = plan.dataset.id == DATASET_ID

    metric_names = [m.name for m in plan.metrics]
    c6_ok = bool(metric_names) and all(m in METRICS for m in metric_names) and plan.primary_metric in METRICS

    param_errors: list[str] = []
    for c in configs:
        unknown = [k for k in c.params if k not in PARAMETER_SPACE]
        if unknown:
            param_errors.append(f"{c.run_id}: unknown params {unknown}")
            continue
        try:
            RAGConfig(**c.params).validate()
        except (TypeError, ValueError) as e:
            param_errors.append(f"{c.run_id}: {e}")
    total_evals = len(configs) * n_questions
    c7_ok = len(configs) <= max_runs and not param_errors

    checks = [
        ValidationCheck(id=1, name="Independent variable", passed=c1_ok, detail=c1),
        ValidationCheck(id=2, name="Measurable dependent variable", passed=c2_ok,
                        detail=f"{plan.dependent_variables}" + (f" — unknown {bad_dv}" if bad_dv else "")),
        ValidationCheck(id=3, name="Baseline", passed=c3_ok,
                        detail=(f"baseline = {plan.baseline.run_id}" if c3_ok else
                                f"baseline '{plan.baseline.run_id}' must be exactly one of the configurations "
                                f"and the only one marked is_baseline (marked: {baselines})")),
        ValidationCheck(id=4, name="At least two configurations", passed=c4_ok,
                        detail=(f"{len(configs)} distinct configurations" if c4_ok else
                                f"{len(configs)} configurations, {distinct} distinct, run_ids unique="
                                f"{len(set(run_ids)) == len(run_ids)}")),
        ValidationCheck(id=5, name="Dataset", passed=c5_ok,
                        detail=f"{plan.dataset.id}" + ("" if c5_ok else f" — only '{DATASET_ID}' is available")),
        ValidationCheck(id=6, name="Measurable metric", passed=c6_ok,
                        detail=f"metrics={metric_names}, primary={plan.primary_metric}"),
        ValidationCheck(id=7, name="Computationally reasonable", passed=c7_ok,
                        detail=(f"{len(configs)} runs × {n_questions} questions = {total_evals} evaluations"
                                + (f" (limit {max_runs} runs)" if len(configs) > max_runs else "")
                                + ("; " + "; ".join(param_errors) if param_errors else ""))),
    ]
    return ValidationReport(checks=checks)
