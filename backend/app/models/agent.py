"""Agent state and event models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .experiment import ExperimentPlan, Hypothesis, QuestionUnderstanding, ValidationReport
from .results import Analysis, NextExperimentProposal, StatisticsReport


class ResearchSource(BaseModel):
    title: str
    url: str
    snippet: str = ""
    score: float | None = None


class ResearchContext(BaseModel):
    searched: bool = False
    query: str = ""
    known_findings: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    research_gap: str = ""
    testable_locally: str = ""
    sources: list[ResearchSource] = Field(default_factory=list)
    note: str = ""


class ExecutionInfo(BaseModel):
    backend: Literal["local_sandbox", "nebius_job"] | None = None
    job_id: str | None = None
    attempts: int = 0
    duration_s: float | None = None
    total_evaluations: int | None = None
    completed_evaluations: int = 0
    sandbox: str = ""
    error: str | None = None
    logs_tail: list[str] = Field(default_factory=list)


class ExperimentState(BaseModel):
    """Everything the agent knows about one experiment (persisted as JSON)."""

    research_question: str
    research_context: ResearchContext | None = None
    understanding: QuestionUnderstanding | None = None
    hypothesis: Hypothesis | None = None
    experiment_plan: ExperimentPlan | None = None
    validation_result: ValidationReport | None = None
    code_validation: ValidationReport | None = None
    generated_code: str | None = None
    code_source: Literal["nemotron", "template"] | None = None
    execution: ExecutionInfo = Field(default_factory=ExecutionInfo)
    statistics: StatisticsReport | None = None
    analysis: Analysis | None = None
    next_experiment: NextExperimentProposal | None = None
    seed_proposal: NextExperimentProposal | None = None  # set when created from a parent
    error: str | None = None
    llm_mode: Literal["nemotron", "offline"] = "nemotron"
    use_research: bool = True
    models: dict[str, str] = Field(default_factory=dict)

    # Convenience views matching the documented ExperimentState fields
    @property
    def variables(self) -> list[Any]:
        return self.experiment_plan.independent_variables if self.experiment_plan else []

    @property
    def conclusion(self) -> str | None:
        return self.analysis.conclusion if self.analysis else None


EventType = Literal[
    "status", "stage", "tool_call", "tool_result", "llm_call", "progress", "log",
    "warning", "error", "retry",
]


class AgentEvent(BaseModel):
    id: int | None = None
    experiment_id: str
    event_type: EventType
    message: str
    stage: str | None = None
    tool: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime
