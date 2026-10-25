import json

import pytest

from app.evaluation.grounding import find_ungrounded
from app.evaluation.metrics import ResultParseError, extract_result_block, parse_results
from app.evaluation.statistics import (
    compute_statistics,
    mcnemar_exact,
    paired_bootstrap_ci,
    pct_change,
    wilson_interval,
)
from app.models.experiment import ExperimentPlan

from .fakes import PLAN


def run(run_id, k, correct_flags):
    n = len(correct_flags)
    pq = [{"question_id": f"q{i:03d}", "expected": "x", "predicted": "x" if c else "y", "correct": bool(c),
           "answer_in_context": True, "context_chunks": k, "context_tokens": 10 * k, "latency_ms": 0.1}
          for i, c in enumerate(correct_flags)]
    acc = sum(correct_flags) / n
    return {"run_id": run_id, "configuration": {"retrieval_k": k},
            "metrics": {"accuracy": acc, "retrieval_recall": 1.0, "context_tokens": 10.0 * k, "latency_ms": 0.1,
                        "est_llm_latency_ms": 180 + 1.2 * k, "n_questions": n, "n_correct": sum(correct_flags)},
            "per_question": pq}


def raw_results():
    base = [1] * 20 + [0] * 20                 # 50%
    better = [1] * 20 + [1] * 12 + [0] * 8     # 80% (gains 12, loses 0)
    plateau = [1] * 20 + [1] * 11 + [0] * 9    # 77.5%
    return {"experiment_id": "exp_x", "seed": 42, "dataset_version": "rag-eval-v1",
            "runs": [run("k3", 3, base), run("k10", 10, better), run("k20", 20, plateau)]}


# --- primitives ---------------------------------------------------------------------------

def test_pct_change_and_baseline_difference():
    assert pct_change(0.72, 0.83) == pytest.approx(15.277, rel=1e-3)
    assert pct_change(0, 1) is None


def test_wilson_interval_bounds():
    lo, hi = wilson_interval(29, 40)
    assert 0.55 < lo < 0.58 and 0.83 < hi < 0.85
    assert wilson_interval(0, 0) == (0.0, 0.0)


def test_mcnemar_exact():
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(8, 0) == pytest.approx(2 / 2**8)
    assert mcnemar_exact(5, 5) == 1.0


def test_bootstrap_is_deterministic():
    a, b = [0, 1] * 20, [1, 1] * 20
    assert paired_bootstrap_ci(a, b) == paired_bootstrap_ci(a, b)
    lo, hi = paired_bootstrap_ci(a, b)
    assert lo <= 0.5 <= hi


# --- report -------------------------------------------------------------------------------

def test_compute_statistics_report():
    results = parse_results(raw_results(), ["k3", "k10", "k20"])
    plan = ExperimentPlan.model_validate(PLAN)
    rep = compute_statistics(results, plan)
    assert rep.baseline_run_id == "k3"
    assert rep.best_run_id == "k10"
    k10 = next(c for c in rep.comparisons if c.run_id == "k10")
    assert k10.absolute_diff_pp == 30.0
    assert k10.relative_change_pct == 60.0
    assert (k10.wins, k10.losses) == (12, 0)
    assert k10.significant
    assert rep.ordered_variable == "retrieval_k"
    assert [s.delta_pp for s in rep.trend] == [30.0, -2.5]
    assert rep.monotonic == "non_monotonic"
    assert rep.diminishing_returns
    assert rep.peak_run_id == "k10"
    assert any("+30.0 pp" in f for f in rep.facts)


def test_grounding_accepts_real_numbers_and_flags_invented_ones():
    rep = compute_statistics(parse_results(raw_results()), ExperimentPlan.model_validate(PLAN))
    ok = ["Accuracy rose from 50.0% to 80.0% (+30.0 pp, +60.0% relative) when k went from 3 to 10."]
    assert find_ungrounded(ok, rep) == []
    bad = ["Accuracy reached 91.2% at k=10, a 37 point gain."]
    assert find_ungrounded(bad, rep) == ["37", "91.2"]


# --- result parsing -----------------------------------------------------------------------

def test_extract_result_block():
    payload = {"a": 1}
    text = f"noise\n@@EOS_RESULT_BEGIN\n{json.dumps(payload)}\n@@EOS_RESULT_END\n"
    assert extract_result_block(text) == payload
    with pytest.raises(ResultParseError):
        extract_result_block("no block here")


def test_parse_results_rejects_wrong_schema():
    with pytest.raises(ResultParseError):
        parse_results({"experiment_id": "x", "runs": []})


def test_parse_results_rejects_tampered_metrics():
    raw = raw_results()
    raw["runs"][0]["metrics"]["accuracy"] = 0.99
    with pytest.raises(ResultParseError, match="recomputable"):
        parse_results(raw)


def test_parse_results_rejects_runs_not_in_plan():
    with pytest.raises(ResultParseError, match="do not match plan"):
        parse_results(raw_results(), ["k3", "k10", "k50"])
