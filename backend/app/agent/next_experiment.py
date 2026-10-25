"""Close the loop: propose the next experiment from measured evidence."""

from __future__ import annotations

import json

from pydantic import ValidationError

from ..execution.runtime.experimentos_sdk.rag import RAGConfig
from ..llm.nebius_client import LLMError
from ..models.experiment import PARAMETER_SPACE, ExperimentPlan, Hypothesis, RunConfiguration
from ..models.results import Analysis, NextExperimentProposal, StatisticsReport
from . import offline, prompts
from .analyzer import stats_payload
from .context import AgentContext
from .hypothesis import _short


def _normalise_parameter(value: str) -> str:
    """Accept 'reranker (cross_lite)' or 'Reranker' as 'reranker' — saves a paid retry."""
    v = value.strip().lower()
    if v in PARAMETER_SPACE:
        return v
    # Longest name first so 'rerank_top_n' wins over 'reranker'-like substrings.
    for name in sorted(PARAMETER_SPACE, key=len, reverse=True):
        if name in v:
            return name
    return value


def proposal_problems(p: NextExperimentProposal) -> list[str]:
    problems: list[str] = []
    if p.varied_parameter not in PARAMETER_SPACE:
        problems.append(f"varied_parameter must be one of {sorted(PARAMETER_SPACE)}")
    if not 2 <= len(p.configurations) <= 6:
        problems.append("configurations must contain 2 to 6 runs")
    runs: list[RunConfiguration] = []
    for c in p.configurations:
        try:
            r = RunConfiguration.model_validate(c)
        except ValidationError as e:
            problems.append(f"invalid configuration {c.get('run_id')!r}: {_short(e)}")
            continue
        unknown = [k for k in r.params if k not in PARAMETER_SPACE]
        if unknown:
            problems.append(f"{r.run_id}: unknown params {unknown}")
            continue
        try:
            RAGConfig(**r.params).validate()
        except (TypeError, ValueError) as e:
            problems.append(f"{r.run_id}: {e}")
        runs.append(r)
    if runs and sum(r.is_baseline for r in runs) != 1:
        problems.append("exactly one configuration must have is_baseline=true")
    if len({r.run_id for r in runs}) != len(runs):
        problems.append("run_ids must be unique")
    return problems


async def create_next_experiment(
    ctx: AgentContext,
    family: str,
    question: str,
    hypothesis: Hypothesis,
    plan: ExperimentPlan,
    stats: StatisticsReport,
    analysis: Analysis,
) -> NextExperimentProposal:
    if ctx.offline:
        return offline.next_experiment(family, stats)

    best = next(r for r in stats.runs if r.run_id == stats.best_run_id)
    user = "\n\n".join([
        f"Previous research question: {question}",
        f"Previous hypothesis: {hypothesis.statement}",
        f"Verdict: {analysis.hypothesis_status} — {analysis.summary}",
        "Key findings:\n- " + "\n- ".join(f.statement for f in analysis.key_findings),
        f"Best configuration so far: {best.run_id} {json.dumps(best.configuration)}",
        "Measured facts:\n- " + "\n- ".join(stats.facts),
        "Compact statistics: " + json.dumps(stats_payload(stats), separators=(",", ":")),
    ])
    feedback = ""
    for attempt in range(1, ctx.max_attempts + 1):
        try:
            raw = await ctx.llm.complete_json(
                task="create_next_experiment", tier="reasoning", system=prompts.fmt(prompts.NEXT_SYSTEM),
                user=user + (f"\n\n{feedback}" if feedback else ""), max_tokens=3072,
            )
            raw["varied_parameter"] = _normalise_parameter(str(raw.get("varied_parameter", "")))
            p = NextExperimentProposal.model_validate(raw)
            problems = proposal_problems(p)
            if not problems:
                return p
            feedback = "Your previous proposal was not executable:\n- " + "\n- ".join(problems)
        except (ValidationError, LLMError) as e:
            feedback = f"Your previous output was invalid: {_short(e)}"
        await ctx.emit("retry", f"Next-experiment proposal invalid (attempt {attempt}/{ctx.max_attempts}).",
                       stage="next", feedback=feedback[:400])
    await ctx.emit("warning", "Using the rule-based next-experiment chain.", stage="next")
    return offline.next_experiment(family, stats)
