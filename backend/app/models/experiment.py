"""Experiment domain models: lifecycle, hypothesis, plan and validation."""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ExperimentStatus(str, Enum):
    CREATED = "CREATED"
    PLANNING = "PLANNING"
    VALIDATING = "VALIDATING"
    GENERATING_CODE = "GENERATING_CODE"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    ANALYZING = "ANALYZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def terminal(self) -> bool:
        return self in TERMINAL_STATUSES


TERMINAL_STATUSES = {ExperimentStatus.COMPLETED, ExperimentStatus.FAILED, ExperimentStatus.CANCELLED}

_S = ExperimentStatus
ALLOWED_TRANSITIONS: dict[ExperimentStatus, set[ExperimentStatus]] = {
    _S.CREATED: {_S.PLANNING},
    _S.PLANNING: {_S.VALIDATING},
    # VALIDATING -> PLANNING: plan revision after a failed validation.
    _S.VALIDATING: {_S.GENERATING_CODE, _S.PLANNING},
    _S.GENERATING_CODE: {_S.QUEUED},
    _S.QUEUED: {_S.RUNNING},
    # RUNNING -> GENERATING_CODE: code correction after a runtime failure.
    _S.RUNNING: {_S.ANALYZING, _S.GENERATING_CODE},
    _S.ANALYZING: {_S.COMPLETED},
    _S.COMPLETED: set(),
    _S.FAILED: set(),
    _S.CANCELLED: set(),
}
for _st in ExperimentStatus:
    if not _st.terminal:
        ALLOWED_TRANSITIONS[_st] |= {_S.FAILED, _S.CANCELLED}


class InvalidTransition(Exception):
    pass


def check_transition(current: ExperimentStatus, new: ExperimentStatus) -> None:
    if new not in ALLOWED_TRANSITIONS[current]:
        raise InvalidTransition(f"illegal status transition {current.value} -> {new.value}")


# ---------------------------------------------------------------------------------------
# The experiment space the bundled runtime can execute. Used for prompts and validation.
# ---------------------------------------------------------------------------------------

PARAMETER_SPACE: dict[str, dict[str, Any]] = {
    "retrieval_k": {"type": "int", "min": 1, "max": 50, "default": 5,
                    "description": "number of chunks retrieved per question (retrieval depth)"},
    "chunk_size": {"type": "int", "min": 8, "max": 512, "default": 128,
                   "description": "chunk length in words"},
    "chunk_overlap": {"type": "int", "min": 0, "max": 256, "default": 0,
                      "description": "overlapping words between consecutive chunks (< chunk_size)"},
    "retriever": {"type": "enum", "values": ["bm25", "embedding", "hybrid"], "default": "bm25",
                  "description": "bm25 = lexical; embedding = hashed char-trigram dense vectors; hybrid = reciprocal-rank fusion"},
    "reranker": {"type": "enum", "values": ["none", "cross_lite"], "default": "none",
                 "description": "cross_lite = entity/phrase-aware reranker over retrieved chunks"},
    "rerank_top_n": {"type": "int|null", "min": 1, "max": 50, "default": None,
                     "description": "chunks kept after reranking (<= retrieval_k); null keeps all"},
    "max_context_tokens": {"type": "int", "min": 64, "max": 32768, "default": 4096,
                           "description": "reader context budget in tokens"},
    "reader_position_bias": {"type": "float", "min": 0.0, "max": 0.9, "default": 0.3,
                             "description": "reader's lost-in-the-middle attention penalty (0 = none)"},
}

METRICS: dict[str, dict[str, str]] = {
    "accuracy": {"goal": "maximize", "description": "fraction of questions answered exactly right"},
    "retrieval_recall": {"goal": "maximize", "description": "fraction of questions whose answer appears in the context"},
    "context_tokens": {"goal": "minimize", "description": "mean tokens of retrieved context per question"},
    "latency_ms": {"goal": "minimize", "description": "measured mean pipeline latency per question (ms)"},
    "est_llm_latency_ms": {"goal": "minimize", "description": "modelled reader latency: 180ms + 0.12ms/context token"},
}

DATASET_ID = "rag-eval-v1"


# ---------------------------------------------------------------------------------------
# Agent outputs
# ---------------------------------------------------------------------------------------

ExperimentFamily = Literal[
    "retrieval_depth", "reranking", "chunk_size", "chunk_overlap", "retriever",
    "context_budget", "reader_position_bias", "other",
]


class QuestionUnderstanding(BaseModel):
    experiment_family: ExperimentFamily
    independent_variable: str
    dependent_variable: str = "accuracy"
    summary: str = Field(min_length=5)
    in_scope: bool = True
    scope_note: str = ""


class Hypothesis(BaseModel):
    statement: str = Field(min_length=30, max_length=600)
    independent_variable: str
    dependent_variable: str
    expected_direction: Literal["increase", "decrease", "non_monotonic", "no_change"]
    expected_relationship: str = Field(min_length=5)
    rationale: str = ""

    @field_validator("independent_variable")
    @classmethod
    def _iv_known(cls, v: str) -> str:
        if v not in PARAMETER_SPACE:
            raise ValueError(f"independent_variable must be one of {sorted(PARAMETER_SPACE)}")
        return v

    @field_validator("dependent_variable")
    @classmethod
    def _dv_known(cls, v: str) -> str:
        if v not in METRICS:
            raise ValueError(f"dependent_variable must be one of {sorted(METRICS)}")
        return v


class Variable(BaseModel):
    name: str
    description: str = ""
    values: list[Any] = Field(default_factory=list)


_RUN_ID = re.compile(r"^[a-z0-9_]{1,40}$")


class RunConfiguration(BaseModel):
    run_id: str
    label: str
    params: dict[str, Any]
    is_baseline: bool = False

    @field_validator("run_id")
    @classmethod
    def _run_id(cls, v: str) -> str:
        v = v.strip().lower()
        if not _RUN_ID.match(v):
            raise ValueError("run_id must match ^[a-z0-9_]{1,40}$")
        return v


class BaselineSpec(BaseModel):
    run_id: str
    description: str


class DatasetSpec(BaseModel):
    id: str = DATASET_ID
    name: str = "RAG Retrieval Evaluation (synthetic)"
    n_questions: int | None = None


class MetricSpec(BaseModel):
    name: str
    goal: Literal["maximize", "minimize"] = "maximize"
    description: str = ""


class ExperimentPlan(BaseModel):
    hypothesis: str
    objective: str
    independent_variables: list[Variable]
    dependent_variables: list[str]
    control_variables: list[str]
    baseline: BaselineSpec
    configurations: list[RunConfiguration]
    dataset: DatasetSpec = Field(default_factory=DatasetSpec)
    metrics: list[MetricSpec]
    primary_metric: str = "accuracy"
    success_criteria: str
    estimated_runs: int = 0
    seed: int = 42

    @model_validator(mode="after")
    def _derive(self) -> "ExperimentPlan":
        self.estimated_runs = len(self.configurations)
        base_ids = {c.run_id for c in self.configurations if c.is_baseline}
        if not base_ids and any(c.run_id == self.baseline.run_id for c in self.configurations):
            for c in self.configurations:
                c.is_baseline = c.run_id == self.baseline.run_id
        return self


class ValidationCheck(BaseModel):
    id: int
    name: str
    passed: bool
    detail: str = ""


class ValidationReport(BaseModel):
    checks: list[ValidationCheck]

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failures(self) -> list[str]:
        return [f"{c.name}: {c.detail}" for c in self.checks if not c.passed]
