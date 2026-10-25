"""Measured results, deterministic statistics and grounded analysis models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class RunMetrics(BaseModel):
    accuracy: float = Field(ge=0, le=1)
    retrieval_recall: float = Field(ge=0, le=1)
    context_tokens: float = Field(ge=0)
    latency_ms: float = Field(ge=0)
    est_llm_latency_ms: float = Field(ge=0)
    n_questions: int = Field(ge=1)
    n_correct: int = Field(ge=0)


class QuestionRecord(BaseModel):
    question_id: str
    question_style: str | None = None
    expected: str
    predicted: str
    correct: bool
    answer_in_context: bool
    gold_position: int | None = None
    answer_position: int | None = None
    context_chunks: int
    context_tokens: int
    latency_ms: float


class RunResult(BaseModel):
    run_id: str
    configuration: dict[str, Any]
    metrics: RunMetrics
    per_question: list[QuestionRecord]


class ExperimentResults(BaseModel):
    """Exact schema the sandboxed experiment must emit (validated, never trusted raw)."""

    experiment_id: str
    seed: int | None = None
    dataset_version: str | None = None
    runs: list[RunResult] = Field(min_length=1)
    metrics: dict[str, RunMetrics] = Field(default_factory=dict)
    artifacts: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------------------
# Deterministic statistics (computed in Python, never by the LLM)
# ---------------------------------------------------------------------------------------


class RunStatistics(BaseModel):
    run_id: str
    label: str
    is_baseline: bool
    configuration: dict[str, Any]
    n: int
    accuracy: float
    accuracy_ci95: tuple[float, float]
    retrieval_recall: float
    context_tokens: float
    est_llm_latency_ms: float
    latency_ms: float


class Comparison(BaseModel):
    run_id: str
    baseline_run_id: str
    metric: str
    baseline_value: float
    value: float
    absolute_diff: float            # in metric units (accuracy: fraction)
    absolute_diff_pp: float | None  # percentage points (proportion metrics only)
    relative_change_pct: float | None
    diff_ci95: tuple[float, float] | None  # paired bootstrap CI of the difference
    mcnemar_p: float | None         # exact McNemar test on paired correctness
    wins: int                       # questions correct here but wrong in baseline
    losses: int                     # questions wrong here but correct in baseline
    significant: bool


class TrendStep(BaseModel):
    from_run: str
    to_run: str
    from_value: Any
    to_value: Any
    delta_pp: float


class StatisticsReport(BaseModel):
    primary_metric: str
    baseline_run_id: str
    runs: list[RunStatistics]
    comparisons: list[Comparison]
    best_run_id: str
    worst_run_id: str
    accuracy_mean: float
    accuracy_median: float
    accuracy_std: float
    ordered_variable: str | None = None
    trend: list[TrendStep] = Field(default_factory=list)
    peak_run_id: str | None = None
    diminishing_returns: bool = False
    monotonic: Literal["increasing", "decreasing", "non_monotonic", "flat", "n/a"] = "n/a"
    facts: list[str] = Field(default_factory=list)  # human-readable, citable facts


# ---------------------------------------------------------------------------------------
# Analysis & next experiment
# ---------------------------------------------------------------------------------------

HypothesisStatus = Literal["SUPPORTED", "PARTIALLY_SUPPORTED", "REJECTED", "INCONCLUSIVE"]


class Finding(BaseModel):
    statement: str = Field(min_length=5)
    evidence: list[str] = Field(default_factory=list)  # run_ids backing this finding


class NextExperimentProposal(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    research_question: str = Field(min_length=10)
    hypothesis: str = Field(min_length=20)
    rationale: str = Field(min_length=10)
    varied_parameter: str
    baseline: dict[str, Any]   # {"label": ..., "params": {...}}
    treatment: dict[str, Any]  # {"label": ..., "params": {...}}
    configurations: list[dict[str, Any]] = Field(default_factory=list)


class Analysis(BaseModel):
    summary: str = Field(min_length=10)
    hypothesis_status: HypothesisStatus
    status_rationale: str = ""
    key_findings: list[Finding] = Field(min_length=1)
    evidence: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    conclusion: str = ""
    next_experiment: NextExperimentProposal | None = None
    grounding: dict[str, Any] = Field(default_factory=dict)
    source: Literal["nemotron", "offline"] = "nemotron"
