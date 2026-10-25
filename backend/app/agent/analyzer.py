"""Grounded analysis of measured results.

Nemotron interprets the deterministic statistics. Its output is then checked:
every number must match a computed value and every cited run must exist. If
the model keeps citing numbers that aren't in the evidence, the agent falls back
to a rule-based analysis instead of publishing an ungrounded claim.
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from ..evaluation.grounding import analysis_texts, find_ungrounded, unknown_run_ids
from ..llm.nebius_client import LLMError
from ..models.experiment import ExperimentPlan, Hypothesis
from ..models.results import Analysis, StatisticsReport
from . import offline, prompts
from .context import AgentContext
from .hypothesis import _short


def varied_keys(configs: list[dict]) -> list[str]:
    keys = sorted({k for c in configs for k in c})
    return [k for k in keys if len({json.dumps(c.get(k)) for c in configs}) > 1]


def stats_payload(stats: StatisticsReport) -> dict:
    """Compact statistics for prompts. The readable facts are sent separately, so this carries only
    what the facts don't: per-run numbers keyed by the parameters that actually vary."""
    keys = varied_keys([r.configuration for r in stats.runs])
    return {
        "baseline": stats.baseline_run_id,
        "best": stats.best_run_id,
        "pattern": stats.monotonic,
        "diminishing_returns": stats.diminishing_returns,
        "runs": [{"id": r.run_id, **{k: r.configuration.get(k) for k in keys},
                  "acc": round(r.accuracy, 4), "recall": round(r.retrieval_recall, 4),
                  "ctx_tokens": round(r.context_tokens)} for r in stats.runs],
        "vs_baseline": [{"id": c.run_id, "diff_pp": c.absolute_diff_pp, "p": c.mcnemar_p,
                         "significant": c.significant} for c in stats.comparisons],
    }


def apply_statistical_guard(a: Analysis, hyp: Hypothesis, stats: StatisticsReport) -> Analysis:
    """A SUPPORTED verdict on a directional hypothesis needs at least one significant difference."""
    if (a.hypothesis_status == "SUPPORTED" and hyp.expected_direction != "no_change"
            and not any(c.significant for c in stats.comparisons)):
        a.grounding["status_adjusted"] = "SUPPORTED → INCONCLUSIVE: no comparison reached p < 0.05"
        a.status_rationale = (a.status_rationale + " [Adjusted by statistical guard: no difference versus the "
                              "baseline was statistically significant (exact McNemar p < 0.05).]").strip()
        a.hypothesis_status = "INCONCLUSIVE"
    return a


async def analyze_results(
    ctx: AgentContext, question: str, hypothesis: Hypothesis, plan: ExperimentPlan, stats: StatisticsReport
) -> Analysis:
    if ctx.offline:
        return offline.analysis(hypothesis, stats)

    user = "\n\n".join([
        f"Research question: {question}",
        f"Hypothesis: {hypothesis.statement} (expected direction: {hypothesis.expected_direction})",
        f"Success criteria: {plan.success_criteria}",
        "MEASURED FACTS (the only numbers you may use):\n- " + "\n- ".join(stats.facts),
        "Compact statistics: " + json.dumps(stats_payload(stats), separators=(",", ":")),
    ])
    feedback = ""
    for attempt in range(1, ctx.max_attempts + 1):
        try:
            raw = await ctx.llm.complete_json(
                task="analyze_results", tier="reasoning", system=prompts.ANALYSIS_SYSTEM,
                user=user + (f"\n\n{feedback}" if feedback else ""), max_tokens=3072,
            )
            raw.pop("next_experiment", None)
            a = Analysis.model_validate(raw)
        except (ValidationError, LLMError) as e:
            feedback = f"Your previous output was invalid: {_short(e)}. Follow the JSON keys exactly."
            await ctx.emit("retry", f"Analysis output invalid (attempt {attempt}/{ctx.max_attempts}).", stage="analysis")
            continue

        ungrounded = find_ungrounded(analysis_texts(a), stats)
        bad_runs = unknown_run_ids(a, stats)
        if not ungrounded and not bad_runs:
            a.source = "nemotron"
            a.grounding = {"verified": True, "attempts": attempt, "ungrounded_numbers": [],
                           "checked_against": "computed statistics"}
            return apply_statistical_guard(a, hypothesis, stats)
        feedback = ("Your previous analysis was rejected because it is not grounded in the measurements. "
                    + (f"These numbers do not appear in the facts: {ungrounded}. " if ungrounded else "")
                    + (f"These run_ids do not exist: {bad_runs}. " if bad_runs else "")
                    + "Use only numbers from MEASURED FACTS.")
        await ctx.emit("retry", f"Analysis cited unverifiable values {ungrounded or bad_runs} "
                       f"(attempt {attempt}/{ctx.max_attempts}). Requesting a grounded revision...",
                       stage="analysis", ungrounded=ungrounded, unknown_runs=bad_runs)

    await ctx.emit("warning", "Nemotron analysis could not be fully grounded — publishing the rule-based "
                   "analysis computed directly from the statistics instead.", stage="analysis")
    a = offline.analysis(hypothesis, stats)
    a.grounding = {"verified": True, "fallback": True, "attempts": ctx.max_attempts}
    return a
