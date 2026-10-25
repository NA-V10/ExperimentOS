"""Tavily research discovery: real runtime HTTP call shape, caching, and the agent integration."""

import json

import httpx

from app.research.tavily import TAVILY_URL, TavilyClient

from .conftest import wait_terminal
from .fakes import FakeLLM

RESULTS = {"results": [
    {"title": "Lost in the Middle", "url": "https://arxiv.org/abs/2307.03172",
     "content": "Performance degrades when relevant information is in the middle of long contexts.", "score": 0.91},
    {"title": "Reranking for RAG", "url": "https://example.org/rerank", "content": "Rerankers improve precision.",
     "score": 0.8},
    {"title": "no url", "url": "", "content": "dropped"},
]}


def tavily_transport(seen: list):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append({"url": str(request.url), "auth": request.headers.get("authorization"),
                     "body": json.loads(request.content)})
        return httpx.Response(200, json=RESULTS)
    return httpx.MockTransport(handler)


async def test_tavily_search_makes_authenticated_runtime_call_and_caches(tmp_path):
    seen: list = []
    client = TavilyClient("tvly-test", max_results=5, transport=tavily_transport(seen), cache_dir=tmp_path)
    sources = await client.search("rag retrieval depth")
    assert seen[0]["url"] == TAVILY_URL
    assert seen[0]["auth"] == "Bearer tvly-test"
    assert seen[0]["body"]["query"] == "rag retrieval depth" and seen[0]["body"]["max_results"] == 5
    assert [s.url for s in sources] == ["https://arxiv.org/abs/2307.03172", "https://example.org/rerank"]
    assert client.last_cached is False

    again = await client.search("rag retrieval depth")
    assert len(seen) == 1 and client.last_cached is True  # no second credit spent
    assert [s.title for s in again] == [s.title for s in sources]

    await client.search("a different question")
    assert len(seen) == 2


def test_experiment_uses_tavily_evidence(settings):
    seen: list = []
    tavily = TavilyClient("tvly-test", transport=tavily_transport(seen))
    llm = FakeLLM()
    from app.main import create_app
    from fastapi.testclient import TestClient
    with TestClient(create_app(settings, llm=llm, tavily=tavily)) as c:
        exp = wait_terminal(c, c.post("/experiments", json={
            "research_question": "Does increasing RAG retrieval depth improve answer accuracy?"}).json()["id"])
    assert exp["status"] == "COMPLETED"
    assert len(seen) == 1  # one real search per experiment
    rc = exp["state"]["research_context"]
    assert rc["searched"] and rc["known_findings"] == ["More context can add noise."]
    assert {s["url"] for s in exp["sources"]} == {"https://arxiv.org/abs/2307.03172", "https://example.org/rerank"}
    assert "summarize_research" in llm.calls  # Nemotron summarised the Tavily results
    stage = [e for e in exp["events"] if e["stage"] == "research" and e["event_type"] == "stage"][-1]
    assert stage["data"]["state"] == "completed" and stage["message"].startswith("Tavily: 2 sources")


def test_experiment_continues_when_tavily_fails(settings):
    def boom(request):
        return httpx.Response(500, text="down")
    tavily = TavilyClient("tvly-test", transport=httpx.MockTransport(boom))
    from app.main import create_app
    from fastapi.testclient import TestClient
    with TestClient(create_app(settings, llm=FakeLLM(), tavily=tavily)) as c:
        exp = wait_terminal(c, c.post("/experiments", json={
            "research_question": "Does increasing RAG retrieval depth improve answer accuracy?"}).json()["id"])
    assert exp["status"] == "COMPLETED"
    assert any(e["event_type"] == "warning" and "Tavily search failed" in e["message"] for e in exp["events"])
