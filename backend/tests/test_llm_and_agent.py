import httpx
import pytest

from app.agent.analyzer import analyze_results
from app.agent.code_generator import ExperimentCodeGenerator
from app.agent.context import AgentContext
from app.agent.hypothesis import HypothesisError, create_hypothesis
from app.agent.next_experiment import create_next_experiment, proposal_problems
from app.config import Settings
from app.evaluation.metrics import parse_results
from app.evaluation.statistics import compute_statistics
from app.llm.nebius_client import (
    LLMNotConfigured,
    LLMResponseError,
    NebiusClient,
    extract_code,
    extract_json,
)
from app.models.experiment import ExperimentPlan, Hypothesis, QuestionUnderstanding
from app.models.results import NextExperimentProposal

from .fakes import ANALYSIS, CODE, HYPOTHESIS, NEXT, PLAN, UNGROUNDED_ANALYSIS, UNSAFE_CODE, VAGUE_HYPOTHESIS, FakeLLM
from .test_statistics_and_results import raw_results

U = QuestionUnderstanding(experiment_family="retrieval_depth", independent_variable="retrieval_k", summary="depth")


def ctx_for(llm):
    events = []

    async def emit(t, m, **d):
        events.append((t, m))

    return AgentContext(llm=llm, emit=emit, max_attempts=3), events


# --- LLM response handling ----------------------------------------------------------------

def test_extract_json_handles_reasoning_and_fences():
    assert extract_json('<think>{"no": 1}</think>\n```json\n{"a": {"b": "}"}}\n```') == {"a": {"b": "}"}}
    assert extract_json('Sure! Here it is: {"x": [1, 2]} hope that helps') == {"x": [1, 2]}
    with pytest.raises(LLMResponseError):
        extract_json("no json at all")


def test_extract_code_picks_python_block():
    assert extract_code(CODE).startswith("from experimentos_sdk import")


def test_nebius_client_requires_configuration():
    with pytest.raises(LLMNotConfigured):
        NebiusClient(Settings(_env_file=None, nebius_api_key="", nebius_model=""))


async def test_nebius_client_calls_token_factory_and_reports_usage(tmp_path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        body = __import__("json").loads(request.content)
        seen["model"] = body["model"]
        return httpx.Response(200, json={
            "model": body["model"],
            "choices": [{"message": {"content": '<think>hmm</think>{"ok": true}'}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3},
        })

    calls = []

    async def hook(call):
        calls.append(call)

    s = Settings(_env_file=None, nebius_api_key="k", nebius_model="nvidia/nemotron-big", nebius_fast_model="nvidia/nemotron-small",
                 llm_cache_dir=tmp_path)
    client = NebiusClient(s, on_call=hook, transport=httpx.MockTransport(handler))
    out = await client.complete_json(task="t", system="s", user="u", tier="fast")
    assert out == {"ok": True}
    assert seen["url"].endswith("/v1/chat/completions")
    assert seen["auth"] == "Bearer k"
    assert seen["model"] == "nvidia/nemotron-small"
    assert calls[0].prompt_tokens == 12 and calls[0].model == "nvidia/nemotron-small"

    # An identical request is replayed from the cache: no second API call, labelled as cached.
    seen.clear()
    assert await client.complete_json(task="t", system="s", user="u", tier="fast") == {"ok": True}
    assert seen == {} and calls[1].extra.get("cached") is True
    await client.aclose()


async def test_nebius_client_retries_then_fails():
    attempts = {"n": 0}

    def handler(request):
        attempts["n"] += 1
        return httpx.Response(503, text="busy")

    s = Settings(_env_file=None, nebius_api_key="k", nebius_model="m", llm_max_retries=1, llm_cache=False)
    client = NebiusClient(s, transport=httpx.MockTransport(handler))
    with pytest.raises(Exception, match="failed after retries"):
        await client.complete_text(task="t", system="s", user="u")
    assert attempts["n"] == 2


# --- agent components with a mocked Nemotron -----------------------------------------------

async def test_hypothesis_revision_loop():
    llm = FakeLLM({"create_hypothesis": [VAGUE_HYPOTHESIS, HYPOTHESIS]})
    ctx, events = ctx_for(llm)
    h = await create_hypothesis(ctx, "Does depth help?", U)
    assert h.statement == HYPOTHESIS["statement"]
    assert llm.calls.count("create_hypothesis") == 2
    assert any(t == "retry" and "Regenerating" in m for t, m in events)


async def test_hypothesis_gives_up_after_three_attempts():
    llm = FakeLLM({"create_hypothesis": [VAGUE_HYPOTHESIS]})
    ctx, _ = ctx_for(llm)
    with pytest.raises(HypothesisError):
        await create_hypothesis(ctx, "Does depth help?", U)
    assert llm.calls.count("create_hypothesis") == 3


async def test_codegen_requests_correction_then_falls_back_to_template():
    plan = ExperimentPlan.model_validate(PLAN)
    llm = FakeLLM({"generate_experiment_code": [UNSAFE_CODE, CODE]})
    ctx, events = ctx_for(llm)
    code, source = await ExperimentCodeGenerator().generate(ctx, plan)
    assert source == "nemotron" and "import os" not in code
    assert any("Requesting correction" in m for _, m in events)

    llm = FakeLLM({"generate_experiment_code": [UNSAFE_CODE]})
    ctx, _ = ctx_for(llm)
    code, source = await ExperimentCodeGenerator().generate(ctx, plan)
    assert source == "template"


def _stats():
    plan = ExperimentPlan.model_validate(PLAN)
    return plan, compute_statistics(parse_results(raw_results()), plan)


async def test_analysis_must_be_grounded():
    plan, stats = _stats()
    hyp = Hypothesis.model_validate(HYPOTHESIS)
    llm = FakeLLM({"analyze_results": [UNGROUNDED_ANALYSIS, ANALYSIS]})
    ctx, events = ctx_for(llm)
    a = await analyze_results(ctx, "q", hyp, plan, stats)
    assert a.source == "nemotron" and a.grounding["verified"] and a.grounding["attempts"] == 2
    assert any("unverifiable" in m for _, m in events)


async def test_analysis_falls_back_when_never_grounded():
    plan, stats = _stats()
    llm = FakeLLM({"analyze_results": [UNGROUNDED_ANALYSIS]})
    ctx, _ = ctx_for(llm)
    a = await analyze_results(ctx, "q", Hypothesis.model_validate(HYPOTHESIS), plan, stats)
    assert a.source == "offline" and a.grounding["fallback"]


async def test_statistical_guard_downgrades_unsupported_claims():
    plan, stats = _stats()
    for c in stats.comparisons:
        c.significant = False
    llm = FakeLLM({"analyze_results": [{**ANALYSIS, "hypothesis_status": "SUPPORTED"}]})
    ctx, _ = ctx_for(llm)
    a = await analyze_results(ctx, "q", Hypothesis.model_validate(HYPOTHESIS), plan, stats)
    assert a.hypothesis_status == "INCONCLUSIVE" and "status_adjusted" in a.grounding


async def test_next_experiment_validation_and_fallback():
    plan, stats = _stats()
    hyp = Hypothesis.model_validate(HYPOTHESIS)
    from app.agent import offline
    analysis = offline.analysis(hyp, stats)
    bad = {**NEXT, "configurations": [{"run_id": "x", "label": "x", "params": {"temperature": 0.7}, "is_baseline": True}]}
    assert proposal_problems(NextExperimentProposal.model_validate(bad))

    ctx, _ = ctx_for(FakeLLM({"create_next_experiment": [bad, NEXT]}))
    p = await create_next_experiment(ctx, "retrieval_depth", "q", hyp, plan, stats, analysis)
    assert p.title == NEXT["title"]

    ctx, _ = ctx_for(FakeLLM({"create_next_experiment": [bad]}))
    p = await create_next_experiment(ctx, "retrieval_depth", "q", hyp, plan, stats, analysis)
    assert p.varied_parameter == "reranker" and not proposal_problems(p)


async def test_next_experiment_accepts_descriptive_parameter_name():
    plan, stats = _stats()
    hyp = Hypothesis.model_validate(HYPOTHESIS)
    from app.agent import offline
    llm = FakeLLM({"create_next_experiment": [{**NEXT, "varied_parameter": "reranker (cross_lite vs none)"}]})
    ctx, _ = ctx_for(llm)
    p = await create_next_experiment(ctx, "retrieval_depth", "q", hyp, plan, stats, offline.analysis(hyp, stats))
    assert p.varied_parameter == "reranker" and llm.calls.count("create_next_experiment") == 1
