"""Guardrails: token budget, call cap, concurrency, rate limits, duplicate follow-ups,
input sanitising, plan/result consistency and dataset integrity."""

import json

import httpx
import pytest

from app.agent.analyzer import stats_payload
from app.agent.planner import _normalise, validate_experiment
from app.config import Settings
from app.evaluation.dataset import DatasetIntegrityError, check_dataset
from app.evaluation.metrics import ResultParseError, parse_results
from app.evaluation.statistics import compute_statistics
from app.llm.nebius_client import NebiusClient
from app.llm.usage import LLMBudgetExceeded, UsageTracker
from app.models.experiment import ExperimentPlan, Hypothesis

from .conftest import make_client, wait_terminal
from .fakes import HYPOTHESIS, PLAN, FakeLLM
from .test_statistics_and_results import raw_results

QUESTION = "Does increasing RAG retrieval depth improve answer accuracy?"


def _ok_transport(counter: dict):
    def handler(request):
        counter["n"] = counter.get("n", 0) + 1
        return httpx.Response(200, json={"model": "m", "choices": [{"message": {"content": '{"ok": true}'}}],
                                         "usage": {"prompt_tokens": 600, "completion_tokens": 400, "total_tokens": 1000}})
    return httpx.MockTransport(handler)


# --- token budget & call cap ---------------------------------------------------------------

async def test_daily_token_budget_blocks_requests_before_sending(tmp_path):
    usage = UsageTracker(tmp_path / "usage.json", daily_token_budget=1500)
    s = Settings(_env_file=None, nebius_api_key="k", nebius_model="m", llm_cache=False)
    sent: dict = {}
    client = NebiusClient(s, transport=_ok_transport(sent), usage=usage)
    await client.complete_json(task="a", system="s", user="1")
    await client.complete_json(task="b", system="s", user="2")  # 2,000 used — over budget now
    with pytest.raises(LLMBudgetExceeded, match="token budget"):
        await client.complete_json(task="c", system="s", user="3")
    assert sent["n"] == 2  # the third request was never sent
    assert usage.today() == {"tokens": 2000, "calls": 2}
    # persisted across restarts
    assert UsageTracker(tmp_path / "usage.json", 1500).remaining() == 0
    await client.aclose()


async def test_per_experiment_call_cap_and_cache_exemption(tmp_path):
    s = Settings(_env_file=None, nebius_api_key="k", nebius_model="m", llm_max_calls_per_experiment=2,
                 llm_cache_dir=tmp_path)
    sent: dict = {}
    base = NebiusClient(s, transport=_ok_transport(sent))
    exp = base.with_hook(None)
    await exp.complete_json(task="a", system="s", user="1")
    await exp.complete_json(task="a", system="s", user="1")  # cache hit — free, not counted
    await exp.complete_json(task="b", system="s", user="2")
    with pytest.raises(LLMBudgetExceeded, match="limit of 2"):
        await exp.complete_json(task="c", system="s", user="3")
    # a new experiment gets a fresh allowance
    await base.with_hook(None).complete_json(task="d", system="s", user="4")
    assert sent["n"] == 3
    await base.aclose()


def test_budget_exhaustion_mid_experiment_finishes_on_rule_based_path(settings):
    llm = FakeLLM({"analyze_results": [LLMBudgetExceeded("Daily Nemotron token budget is used up.")]})
    with make_client(settings, llm=llm) as c:
        exp = wait_terminal(c, c.post("/experiments", json={"research_question": QUESTION}).json()["id"])
    assert exp["status"] == "COMPLETED"  # measurements are not thrown away
    assert exp["state"]["analysis"]["source"] == "offline"
    assert any(e["event_type"] == "warning" and e["data"].get("guardrail") == "llm_budget" for e in exp["events"])
    assert "create_next_experiment" not in llm.calls  # Nemotron stays off for the rest of the run


def test_api_refuses_new_experiments_when_budget_is_spent(settings, fake_llm):
    with make_client(settings, llm=fake_llm) as c:
        c.app.state.usage = UsageTracker(settings.work_root / "u.json", daily_token_budget=10)
        c.app.state.usage.record(50)
        r = c.post("/experiments", json={"research_question": QUESTION})
    assert r.status_code == 429 and "budget" in r.json()["detail"]


# --- launch guardrails -----------------------------------------------------------------------

def test_concurrency_limit(settings, fake_llm):
    settings.max_concurrent_experiments = 1
    with make_client(settings, llm=fake_llm) as c:
        c.app.state.orchestrator.tasks["exp_fake"] = object()  # simulate one running experiment
        r = c.post("/experiments", json={"research_question": QUESTION})
        c.app.state.orchestrator.tasks.pop("exp_fake")
    assert r.status_code == 429 and "already running" in r.json()["detail"]


def test_rate_limit(settings, fake_llm):
    settings.experiment_rate_limit_per_minute = 2
    settings.max_concurrent_experiments = 0
    with make_client(settings, llm=fake_llm) as c:
        codes = [c.post("/experiments", json={"research_question": QUESTION}).status_code for _ in range(3)]
        for item in c.get("/experiments").json()["items"]:
            wait_terminal(c, item["id"])
    assert codes == [201, 201, 429]


def test_next_experiment_cannot_be_launched_twice(settings, fake_llm):
    with make_client(settings, llm=fake_llm) as c:
        exp = wait_terminal(c, c.post("/experiments", json={"research_question": QUESTION}).json()["id"])
        first = c.post(f"/experiments/{exp['id']}/next")
        second = c.post(f"/experiments/{exp['id']}/next")
        wait_terminal(c, first.json()["id"])
    assert first.status_code == 201
    assert second.status_code == 409 and second.json()["detail"]["experiment_id"] == first.json()["id"]


@pytest.mark.parametrize("question,ok", [
    ("Does   increasing\x00 RAG​ retrieval\n\tdepth help?", True),
    ("1234567890 !!!! ????", False),
    ("\x00\x01\x02\x03\x04\x05\x06\x07\x08\x0b\x0c abc", False),
])
def test_research_question_is_sanitised(settings, fake_llm, question, ok):
    with make_client(settings, llm=fake_llm) as c:
        r = c.post("/experiments", json={"research_question": question})
        if ok:
            assert r.status_code == 201
            assert r.json()["research_question"] == "Does increasing RAG retrieval depth help?"
            wait_terminal(c, r.json()["id"])
        else:
            assert r.status_code == 422


def test_health_reports_guardrails(settings, fake_llm):
    with make_client(settings, llm=fake_llm) as c:
        g = c.get("/health").json()["guardrails"]
    assert g["daily_token_budget"] == settings.llm_daily_token_budget
    assert g["max_calls_per_experiment"] == settings.llm_max_calls_per_experiment
    assert g["running_experiments"] == 0


def test_detail_can_skip_event_log(settings, fake_llm):
    with make_client(settings, llm=fake_llm) as c:
        exp = wait_terminal(c, c.post("/experiments", json={"research_question": QUESTION}).json()["id"])
        light = c.get(f"/experiments/{exp['id']}?events=false").json()
    assert light["events"] is None and exp["events"]


# --- scientific consistency -------------------------------------------------------------------

def test_results_must_match_planned_parameters():
    planned = {"k3": {"retrieval_k": 3}, "k10": {"retrieval_k": 10}, "k20": {"retrieval_k": 20}}
    raw = raw_results()
    for r in raw["runs"]:
        r["configuration"] = {**json.loads(json.dumps(r["configuration"])), "chunk_size": 128, "chunk_overlap": 0,
                              "retriever": "bm25", "reranker": "none", "rerank_top_n": None,
                              "max_context_tokens": 4096, "reader_position_bias": 0.3}
    parse_results(raw, list(planned), planned)  # matches exactly
    raw["runs"][1]["configuration"]["retrieval_k"] = 5  # code ran k=5 but labelled it k10
    with pytest.raises(ResultParseError, match="differs from the plan"):
        parse_results(raw, list(planned), planned)


def test_plan_must_vary_the_hypothesis_variable():
    plan = ExperimentPlan.model_validate(_normalise(PLAN))
    ok = Hypothesis.model_validate(HYPOTHESIS)
    assert validate_experiment(plan, 40, hypothesis=ok).passed
    off = Hypothesis.model_validate({**HYPOTHESIS, "independent_variable": "chunk_size",
                                     "statement": "Increasing chunk_size from 32 to 128 words will improve accuracy."})
    report = validate_experiment(plan, 40, hypothesis=off)
    assert not report.passed and "never varies it" in report.failures[0]


def test_dataset_integrity_check(tmp_path, settings):
    assert check_dataset(settings.dataset_path)["questions"] == 40
    data = json.loads(settings.dataset_path.read_text(encoding="utf-8"))
    data["questions"][0]["expected_answer"] = "not-in-the-gold-passage"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(DatasetIntegrityError, match="q001"):
        check_dataset(bad)


def test_prompt_statistics_are_compact():
    plan = ExperimentPlan.model_validate(PLAN)
    payload = stats_payload(compute_statistics(parse_results(raw_results()), plan))
    assert payload["runs"][0].keys() == {"id", "retrieval_k", "acc", "recall", "ctx_tokens"}
    assert "facts" not in payload  # facts are sent once, as text
