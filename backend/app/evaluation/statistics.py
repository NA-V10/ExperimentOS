"""Deterministic statistics. The LLM interprets these numbers; it never computes them."""

from __future__ import annotations

import math
import random
import statistics as st
from typing import Any, Sequence

from ..models.experiment import ExperimentPlan
from ..models.results import (
    Comparison,
    ExperimentResults,
    RunStatistics,
    StatisticsReport,
    TrendStep,
)

BOOTSTRAP_SEED = 42
BOOTSTRAP_RESAMPLES = 2000


def mean(xs: Sequence[float]) -> float:
    return float(st.fmean(xs)) if xs else 0.0


def median(xs: Sequence[float]) -> float:
    return float(st.median(xs)) if xs else 0.0


def std(xs: Sequence[float]) -> float:
    return float(st.stdev(xs)) if len(xs) > 1 else 0.0


def pct_change(baseline: float, value: float) -> float | None:
    if baseline == 0:
        return None
    return (value - baseline) / abs(baseline) * 100.0


def wilson_interval(successes: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def mcnemar_exact(wins: int, losses: int) -> float:
    """Two-sided exact McNemar test (binomial test on discordant pairs)."""
    n = wins + losses
    if n == 0:
        return 1.0
    k = min(wins, losses)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def paired_bootstrap_ci(
    a: Sequence[int], b: Sequence[int], resamples: int = BOOTSTRAP_RESAMPLES, seed: int = BOOTSTRAP_SEED
) -> tuple[float, float]:
    """95% CI of mean(b) - mean(a) for paired 0/1 outcomes."""
    n = len(a)
    if n == 0:
        return (0.0, 0.0)
    rng = random.Random(seed)
    diffs = []
    for _ in range(resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        diffs.append(sum(b[i] - a[i] for i in idx) / n)
    diffs.sort()
    return (diffs[int(0.025 * resamples)], diffs[int(0.975 * resamples) - 1])


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _ordered_variable(plan: ExperimentPlan | None, results: ExperimentResults) -> str | None:
    if not plan or not plan.independent_variables:
        return None
    name = plan.independent_variables[0].name
    values = [r.configuration.get(name) for r in results.runs]
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values) and len(set(values)) == len(values):
        return name
    return None


def compute_statistics(results: ExperimentResults, plan: ExperimentPlan | None = None) -> StatisticsReport:
    runs = results.runs
    labels = {c.run_id: c.label for c in plan.configurations} if plan else {}
    run_ids = [r.run_id for r in runs]
    baseline_id = plan.baseline.run_id if plan and plan.baseline.run_id in run_ids else run_ids[0]
    base = next(r for r in runs if r.run_id == baseline_id)
    base_correct = {q.question_id: int(q.correct) for q in base.per_question}

    run_stats: list[RunStatistics] = []
    comparisons: list[Comparison] = []
    facts: list[str] = []

    for r in runs:
        m = r.metrics
        ci = wilson_interval(m.n_correct, m.n_questions)
        run_stats.append(
            RunStatistics(
                run_id=r.run_id,
                label=labels.get(r.run_id, r.run_id),
                is_baseline=r.run_id == baseline_id,
                configuration=r.configuration,
                n=m.n_questions,
                accuracy=m.accuracy,
                accuracy_ci95=(round(ci[0], 4), round(ci[1], 4)),
                retrieval_recall=m.retrieval_recall,
                context_tokens=m.context_tokens,
                est_llm_latency_ms=m.est_llm_latency_ms,
                latency_ms=m.latency_ms,
            )
        )
        facts.append(
            f"{r.run_id}{' (baseline)' if r.run_id == baseline_id else ''}: accuracy {_fmt_pct(m.accuracy)} "
            f"({m.n_correct}/{m.n_questions}, 95% CI {_fmt_pct(ci[0])}–{_fmt_pct(ci[1])}), "
            f"retrieval recall {_fmt_pct(m.retrieval_recall)}, mean context {m.context_tokens:.1f} tokens, "
            f"modelled reader latency {m.est_llm_latency_ms:.1f} ms"
        )

        if r.run_id == baseline_id:
            continue
        own = {q.question_id: int(q.correct) for q in r.per_question}
        shared = [qid for qid in base_correct if qid in own]
        a = [base_correct[q] for q in shared]
        b = [own[q] for q in shared]
        wins = sum(1 for x, y in zip(a, b) if y and not x)
        losses = sum(1 for x, y in zip(a, b) if x and not y)
        p = mcnemar_exact(wins, losses)
        ci_d = paired_bootstrap_ci(a, b)
        diff = m.accuracy - base.metrics.accuracy
        rel = pct_change(base.metrics.accuracy, m.accuracy)
        comparisons.append(
            Comparison(
                run_id=r.run_id,
                baseline_run_id=baseline_id,
                metric="accuracy",
                baseline_value=base.metrics.accuracy,
                value=m.accuracy,
                absolute_diff=round(diff, 4),
                absolute_diff_pp=round(diff * 100, 1),
                relative_change_pct=None if rel is None else round(rel, 1),
                diff_ci95=(round(ci_d[0] * 100, 1), round(ci_d[1] * 100, 1)),
                mcnemar_p=round(p, 4),
                wins=wins,
                losses=losses,
                significant=p < 0.05,
            )
        )
        facts.append(
            f"{r.run_id} vs baseline {baseline_id}: {diff * 100:+.1f} pp accuracy"
            + (f" ({rel:+.1f}% relative)" if rel is not None else "")
            + f", paired 95% CI [{ci_d[0] * 100:+.1f}, {ci_d[1] * 100:+.1f}] pp, {wins} questions gained / "
            f"{losses} lost, exact McNemar p={p:.3f} ({'significant' if p < 0.05 else 'not significant'} at 0.05)"
        )

    accs = [r.metrics.accuracy for r in runs]
    best = max(runs, key=lambda r: (r.metrics.accuracy, -r.metrics.context_tokens))
    worst = min(runs, key=lambda r: (r.metrics.accuracy, r.metrics.context_tokens))
    report = StatisticsReport(
        primary_metric="accuracy",
        baseline_run_id=baseline_id,
        runs=run_stats,
        comparisons=comparisons,
        best_run_id=best.run_id,
        worst_run_id=worst.run_id,
        accuracy_mean=round(mean(accs), 4),
        accuracy_median=round(median(accs), 4),
        accuracy_std=round(std(accs), 4),
        facts=facts,
    )
    facts.append(
        f"Across {len(runs)} runs: mean accuracy {_fmt_pct(report.accuracy_mean)}, median "
        f"{_fmt_pct(report.accuracy_median)}, std {report.accuracy_std * 100:.1f} pp; best {best.run_id} "
        f"({_fmt_pct(best.metrics.accuracy)}), worst {worst.run_id} ({_fmt_pct(worst.metrics.accuracy)})"
    )

    var = _ordered_variable(plan, results)
    if var:
        ordered = sorted(runs, key=lambda r: r.configuration[var])
        steps = [
            TrendStep(
                from_run=x.run_id,
                to_run=y.run_id,
                from_value=x.configuration[var],
                to_value=y.configuration[var],
                delta_pp=round((y.metrics.accuracy - x.metrics.accuracy) * 100, 1),
            )
            for x, y in zip(ordered, ordered[1:])
        ]
        deltas = [s.delta_pp for s in steps]
        if all(abs(d) < 0.05 for d in deltas):
            mono = "flat"
        elif all(d >= 0 for d in deltas):
            mono = "increasing"
        elif all(d <= 0 for d in deltas):
            mono = "decreasing"
        else:
            mono = "non_monotonic"
        peak = max(ordered, key=lambda r: (r.metrics.accuracy, -r.configuration[var]))
        first_gain = next((d for d in deltas if d > 0), None)
        diminishing = bool(
            first_gain is not None
            and len(deltas) >= 2
            and (deltas[-1] <= 0 or deltas[-1] < first_gain / 2)
        )
        report.ordered_variable = var
        report.trend = steps
        report.monotonic = mono
        report.peak_run_id = peak.run_id
        report.diminishing_returns = diminishing
        trend_txt = ", ".join(
            f"{var} {s.from_value}→{s.to_value}: {s.delta_pp:+.1f} pp" for s in steps
        )
        facts.append(
            f"Trend over {var}: {trend_txt}. Accuracy peaks at {var}={peak.configuration[var]} "
            f"({_fmt_pct(peak.metrics.accuracy)}); pattern is {mono.replace('_', '-')}"
            + ("; marginal gains diminish at higher values" if diminishing else "")
        )
    return report


def numeric_values(report: StatisticsReport) -> list[float]:
    """Every number the analysis is allowed to cite, in the units it may be cited in."""
    vals: list[float] = []

    def add(x: Any) -> None:
        if isinstance(x, bool) or x is None:
            return
        if isinstance(x, (int, float)):
            vals.append(float(x))
        elif isinstance(x, (list, tuple)):
            for y in x:
                add(y)
        elif isinstance(x, dict):
            for y in x.values():
                add(y)

    for r in report.runs:
        add(r.configuration)
        for p in (r.accuracy, r.retrieval_recall, *r.accuracy_ci95):
            vals.extend([p, p * 100])
        add([r.n, r.context_tokens, r.est_llm_latency_ms, r.latency_ms])
        vals.append(round(r.accuracy * r.n))
    for c in report.comparisons:
        add([c.absolute_diff_pp, c.relative_change_pct, c.diff_ci95, c.mcnemar_p, c.wins, c.losses,
             c.baseline_value * 100, c.value * 100, c.absolute_diff])
        if c.absolute_diff_pp is not None:
            vals.append(abs(c.absolute_diff_pp))
        if c.relative_change_pct is not None:
            vals.append(abs(c.relative_change_pct))
    for s in report.trend:
        add([s.delta_pp, abs(s.delta_pp), s.from_value, s.to_value])
    for x in (report.accuracy_mean, report.accuracy_median, report.accuracy_std):
        vals.extend([x, x * 100])
    vals.append(len(report.runs))
    return vals
