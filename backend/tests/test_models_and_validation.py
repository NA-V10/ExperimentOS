import pytest
from pydantic import ValidationError

from app.agent import offline
from app.agent.hypothesis import assess_hypothesis
from app.agent.planner import _normalise, validate_experiment
from app.models.experiment import (
    ExperimentPlan,
    ExperimentStatus as S,
    Hypothesis,
    InvalidTransition,
    check_transition,
)

from .fakes import HYPOTHESIS, PLAN


def plan(**overrides) -> ExperimentPlan:
    raw = {**PLAN, **overrides}
    return ExperimentPlan.model_validate(_normalise(raw))


# --- hypothesis schema & quality --------------------------------------------------------

def test_hypothesis_schema_accepts_valid():
    h = Hypothesis.model_validate(HYPOTHESIS)
    assert assess_hypothesis(h) == []


def test_hypothesis_schema_rejects_unknown_variables():
    with pytest.raises(ValidationError):
        Hypothesis.model_validate({**HYPOTHESIS, "independent_variable": "temperature"})
    with pytest.raises(ValidationError):
        Hypothesis.model_validate({**HYPOTHESIS, "dependent_variable": "vibes"})


@pytest.mark.parametrize("statement", [
    "RAG is better with more context when you use it a lot of the time.",
    "Retrieval depth might change accuracy somehow in the experiment we run here.",
])
def test_vague_hypotheses_are_rejected(statement):
    h = Hypothesis.model_validate({**HYPOTHESIS, "statement": statement})
    assert assess_hypothesis(h), "vague hypothesis should fail the quality gate"


# --- plan validation ----------------------------------------------------------------------

def test_valid_plan_passes_all_checks():
    report = validate_experiment(plan(), n_questions=40)
    assert report.passed, report.failures
    assert [c.id for c in report.checks] == [1, 2, 3, 4, 5, 6, 7]


def test_plan_requires_baseline_in_configurations():
    report = validate_experiment(plan(baseline={"run_id": "nope", "description": "x"}), 40)
    assert not report.passed
    assert any("Baseline" in f for f in report.failures)


def test_plan_requires_two_configurations():
    one = [PLAN["configurations"][0]]
    report = validate_experiment(plan(configurations=one), 40)
    assert any("two configurations" in f for f in report.failures)


def test_plan_detects_uncontrolled_variables():
    configs = [
        {"run_id": "k3", "label": "k=3", "params": {"retrieval_k": 3}, "is_baseline": True},
        {"run_id": "k10", "label": "k=10", "params": {"retrieval_k": 10, "chunk_size": 32}},
    ]
    report = validate_experiment(plan(configurations=configs), 40)
    assert any("uncontrolled" in f for f in report.failures)


def test_plan_rejects_unknown_dataset_and_metric():
    report = validate_experiment(plan(dataset={"id": "imagenet"}, metrics=[{"name": "bleu"}]), 40)
    names = " ".join(report.failures)
    assert "Dataset" in names and "Measurable metric" in names


def test_plan_rejects_out_of_range_params_and_too_many_runs():
    configs = [{"run_id": "k3", "label": "a", "params": {"retrieval_k": 3}, "is_baseline": True},
               {"run_id": "k999", "label": "b", "params": {"retrieval_k": 999}}]
    report = validate_experiment(plan(configurations=configs), 40)
    assert any("Computationally reasonable" in f for f in report.failures)
    many = [{"run_id": f"k{i}", "label": str(i), "params": {"retrieval_k": i}, "is_baseline": i == 1}
            for i in range(1, 16)]
    report = validate_experiment(plan(configurations=many, baseline={"run_id": "k1", "description": ""}), 40, max_runs=12)
    assert any("Computationally reasonable" in f for f in report.failures)


@pytest.mark.parametrize("family", list(offline.FAMILIES))
def test_every_offline_family_plan_is_valid(family):
    p = offline.plan(family, offline.hypothesis(family))
    assert validate_experiment(p, 40).passed, (family, validate_experiment(p, 40).failures)
    assert assess_hypothesis(offline.hypothesis(family)) == [], family


def test_offline_classifier():
    assert offline.classify("Does increasing RAG retrieval depth improve answer accuracy?") == "retrieval_depth"
    assert offline.classify("Does reranking help?") == "reranking"
    assert offline.classify("What chunk overlap is best?") == "chunk_overlap"
    assert offline.classify("Is hybrid retrieval better than BM25?") == "retriever"
    assert offline.classify("What is the capital of France?") is None


# --- state machine ------------------------------------------------------------------------

def test_happy_path_transitions_are_legal():
    path = [S.CREATED, S.PLANNING, S.VALIDATING, S.GENERATING_CODE, S.QUEUED, S.RUNNING, S.ANALYZING, S.COMPLETED]
    for a, b in zip(path, path[1:]):
        check_transition(a, b)


def test_revision_loops_are_legal():
    check_transition(S.VALIDATING, S.PLANNING)
    check_transition(S.RUNNING, S.GENERATING_CODE)


@pytest.mark.parametrize("a,b", [(S.CREATED, S.RUNNING), (S.COMPLETED, S.PLANNING), (S.FAILED, S.RUNNING),
                                 (S.PLANNING, S.COMPLETED)])
def test_illegal_transitions_raise(a, b):
    with pytest.raises(InvalidTransition):
        check_transition(a, b)


def test_any_active_state_can_fail_or_cancel():
    for s in S:
        if not s.terminal:
            check_transition(s, S.FAILED)
            check_transition(s, S.CANCELLED)
