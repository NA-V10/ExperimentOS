"""End-to-end: question → plan → (real, sandboxed) execution → results → analysis → next experiment."""

from app.execution.runner import ExecutionOutcome

from .conftest import make_client, wait_terminal
from .fakes import FakeLLM

QUESTION = "Does increasing RAG retrieval depth improve answer accuracy?"


def test_health_reports_configuration_without_secrets(settings):
    settings.nebius_api_key = "super-secret-key"
    with make_client(settings, llm=None) as c:
        body = c.get("/health").json()
    assert body["status"] == "ok" and body["nebius"] == "configured"
    assert body["execution"] == "ready"
    assert "super-secret-key" not in str(body)


def test_full_loop_with_mocked_nemotron(settings, fake_llm):
    with make_client(settings, llm=fake_llm) as c:
        r = c.post("/experiments", json={"research_question": QUESTION})
        assert r.status_code == 201
        exp = wait_terminal(c, r.json()["id"])
        assert exp["status"] == "COMPLETED", exp["error"]
        st = exp["state"]
        assert st["hypothesis"]["independent_variable"] == "retrieval_k"
        assert st["validation_result"]["checks"] and all(ch["passed"] for ch in st["validation_result"]["checks"])
        assert st["code_source"] == "nemotron"
        assert st["analysis"]["grounding"]["verified"]
        assert st["next_experiment"]["title"]

        # Real measurements were persisted and are recomputable.
        res = c.get(f"/experiments/{exp['id']}/results").json()
        assert [r["run_id"] for r in res["runs"]] == ["k3", "k10", "k20"]
        for run in res["runs"]:
            pq = run["per_question"]
            assert run["metrics"]["n_correct"] == sum(q["correct"] for q in pq)

        # Every lifecycle state was emitted as a real event, in order.
        statuses = [e["data"]["status"] for e in exp["events"] if e["event_type"] == "status"]
        assert statuses == ["PLANNING", "VALIDATING", "GENERATING_CODE", "QUEUED", "RUNNING", "ANALYZING", "COMPLETED"]
        tools = {e["tool"] for e in exp["events"] if e["event_type"] == "tool_call"}
        assert {"create_hypothesis", "design_experiment", "validate_experiment", "generate_experiment_code",
                "submit_experiment", "get_experiment_results", "calculate_statistics", "analyze_results",
                "create_next_experiment"} <= tools
        assert any(e["event_type"] == "llm_call" for e in exp["events"])
        assert any(e["event_type"] == "progress" for e in exp["events"])

        # Close the loop.
        nxt = c.post(f"/experiments/{exp['id']}/next")
        assert nxt.status_code == 201
        child = wait_terminal(c, nxt.json()["id"])
        assert child["parent_experiment_id"] == exp["id"]
        assert child["state"]["seed_proposal"]["title"] == st["next_experiment"]["title"]

        listing = c.get("/experiments").json()
        assert listing["dashboard"]["experiments"] == 2


def test_offline_mode_runs_featured_experiment(settings):
    with make_client(settings, llm=None) as c:
        r = c.post("/experiments/featured")
        exp = wait_terminal(c, r.json()["id"])
    assert exp["status"] == "COMPLETED", exp["error"]
    assert exp["llm_mode"] == "offline" and exp["featured"]
    assert exp["state"]["analysis"]["source"] == "offline"
    assert len(exp["results"]) == 4


def test_offline_disabled_returns_configuration_help(settings):
    settings.allow_offline_fallback = False
    with make_client(settings, llm=None) as c:
        r = c.post("/experiments", json={"research_question": QUESTION})
    assert r.status_code == 503 and "NEBIUS_API_KEY" in r.json()["detail"]


def test_out_of_scope_question_fails_gracefully(settings):
    llm = FakeLLM({"understand_question": [{"experiment_family": "other", "independent_variable": "retrieval_k",
                                            "summary": "geography", "in_scope": False,
                                            "scope_note": "Not an AI/ML experiment."}]})
    with make_client(settings, llm=llm) as c:
        exp = wait_terminal(c, c.post("/experiments", json={"research_question": "What is the capital of France?"}).json()["id"])
    assert exp["status"] == "FAILED" and "outside the executable experiment space" in exp["error"]


class AlwaysFails:
    name = "local_sandbox"

    def __init__(self):
        self.calls = 0

    async def execute(self, *, experiment_id, code, attempt, on_event):
        self.calls += 1
        return ExecutionOutcome(ok=False, backend=self.name, error="Timeout: exceeded 1s", timed_out=True)


def test_runtime_failures_stop_after_three_attempts(settings, fake_llm):
    ex = AlwaysFails()
    with make_client(settings, llm=fake_llm, executor=ex) as c:
        exp = wait_terminal(c, c.post("/experiments", json={"research_question": QUESTION}).json()["id"])
    assert exp["status"] == "FAILED"
    assert ex.calls == 3
    assert "could not be safely executed" in exp["error"]
    actions = [e["message"] for e in exp["events"] if e["event_type"] == "error" and "Action:" in e["message"]]
    assert len(actions) == 2 and "Reduce experiment size" in actions[0]


def test_next_requires_completed_experiment_and_404s(settings, fake_llm):
    with make_client(settings, llm=fake_llm) as c:
        assert c.get("/experiments/exp_999").status_code == 404
        assert c.post("/experiments/exp_999/next").status_code == 404
        assert c.post("/experiments", json={"research_question": "short"}).status_code == 422


def test_sse_stream_replays_events(settings, fake_llm):
    with make_client(settings, llm=fake_llm) as c:
        exp = wait_terminal(c, c.post("/experiments", json={"research_question": QUESTION}).json()["id"])
        with c.stream("GET", f"/experiments/{exp['id']}/events") as s:
            body = "".join(s.iter_text())
    assert "event: agent" in body and "Status → COMPLETED" in body and "event: end" in body


def test_datasets_endpoint(settings):
    with make_client(settings, llm=None) as c:
        items = c.get("/datasets").json()["items"]
        assert items[0]["id"] == "rag-eval-v1" and items[0]["n_questions"] == 40
        detail = c.get("/datasets/rag-eval-v1").json()
        assert detail["seed"] == 42 and len(detail["questions"]) == 40
