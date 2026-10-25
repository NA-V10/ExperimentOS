"""Experiment endpoints, including the live SSE event stream."""

from __future__ import annotations

import asyncio
import json
import re
import time
import unicodedata
from collections import defaultdict, deque
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from ..models.agent import ExperimentState
from ..models.experiment import ExperimentStatus

router = APIRouter(prefix="/experiments", tags=["experiments"])

FEATURED_QUESTION = "Does increasing the number of retrieved documents improve RAG answer accuracy?"


class CreateExperiment(BaseModel):
    research_question: str = Field(min_length=10, max_length=500)
    use_research: bool = True
    featured: bool = False

    @field_validator("research_question")
    @classmethod
    def _clean(cls, v: str) -> str:
        """Strip control/format characters and collapse whitespace before the text reaches any prompt."""
        v = "".join(" " if ch.isspace() else ch for ch in v
                    if ch.isspace() or unicodedata.category(ch)[0] != "C")
        v = re.sub(r"\s+", " ", v).strip()
        if len(v) < 10:
            raise ValueError("research question is too short after cleaning (min 10 characters)")
        if not re.search(r"[A-Za-z]{3,}", v):
            raise ValueError("research question must contain words")
        return v


def _deps(request: Request):
    return request.app.state.repo, request.app.state.orchestrator


def _require(repo, exp_id: str) -> dict[str, Any]:
    exp = repo.get_experiment(exp_id)
    if not exp:
        raise HTTPException(404, f"experiment {exp_id} not found")
    return exp


def _ensure_reasoning_available(request: Request) -> str:
    settings = request.app.state.settings
    if request.app.state.llm is not None:
        return "nemotron"
    if settings.allow_offline_fallback:
        return "offline"
    raise HTTPException(503, settings.configuration_help())


def _check_guardrails(request: Request) -> None:
    """Run before every launch: concurrency, per-client rate limit and the daily token budget."""
    s = request.app.state.settings
    orch = request.app.state.orchestrator
    running = len(orch.tasks)
    if s.max_concurrent_experiments and running >= s.max_concurrent_experiments:
        raise HTTPException(429, f"{running} experiment(s) are already running (MAX_CONCURRENT_EXPERIMENTS="
                                 f"{s.max_concurrent_experiments}). Wait for one to finish.")
    if s.experiment_rate_limit_per_minute:
        client = request.client.host if request.client else "unknown"
        if not hasattr(request.app.state, "recent_launches"):
            request.app.state.recent_launches = defaultdict(deque)
        window, now = request.app.state.recent_launches[client], time.monotonic()
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= s.experiment_rate_limit_per_minute:
            raise HTTPException(429, f"Rate limit: at most {s.experiment_rate_limit_per_minute} experiments per "
                                     "minute. Please wait a moment.")
        window.append(now)
    usage = getattr(request.app.state, "usage", None)
    if request.app.state.llm is not None and usage is not None and usage.remaining() == 0:
        raise HTTPException(429, f"Daily Nemotron token budget ({s.llm_daily_token_budget:,}) is used up. "
                                 "It resets at 00:00 UTC (LLM_DAILY_TOKEN_BUDGET).")


def _launch(request: Request, state: ExperimentState, parent_id: str | None = None, featured: bool = False):
    _check_guardrails(request)
    repo, orch = _deps(request)
    exp = repo.create_experiment(state, parent_id=parent_id, execution_mode=request.app.state.settings.execution_mode,
                                 featured=featured)
    orch.start(exp["id"])
    return exp


@router.post("", status_code=201)
async def create_experiment(body: CreateExperiment, request: Request):
    mode = _ensure_reasoning_available(request)
    state = ExperimentState(research_question=body.research_question, llm_mode=mode,
                            use_research=body.use_research)
    return _launch(request, state, featured=body.featured)


@router.post("/featured", status_code=201)
async def run_featured(request: Request):
    """One-click canonical demo: RAG retrieval depth on the bundled DEMO DATASET."""
    mode = _ensure_reasoning_available(request)
    state = ExperimentState(research_question=FEATURED_QUESTION, llm_mode=mode)
    return _launch(request, state, featured=True)


@router.get("")
async def list_experiments(request: Request, limit: int = Query(200, ge=1, le=1000)):
    repo, _ = _deps(request)
    return {"items": repo.list_experiments(limit), "dashboard": repo.dashboard()}


@router.get("/{exp_id}")
async def get_experiment(exp_id: str, request: Request, events: bool = True):
    """``events=false`` skips the event log — the live UI already receives events over SSE."""
    repo, _ = _deps(request)
    exp = _require(repo, exp_id)
    exp["runs"] = repo.list_runs(exp_id)
    exp["results"] = repo.get_results(exp_id, include_raw=False)
    exp["events"] = [e.model_dump(mode="json") for e in repo.list_events(exp_id)] if events else None
    exp["sources"] = repo.list_sources(exp_id)
    exp["children"] = repo.children(exp_id)
    parent = exp.get("parent_experiment_id")
    exp["parent"] = repo.get_experiment(parent) if parent else None
    if exp["parent"]:
        exp["parent"].pop("state", None)
    return exp


@router.get("/{exp_id}/status")
async def get_status(exp_id: str, request: Request):
    repo, _ = _deps(request)
    exp = _require(repo, exp_id)
    st = exp["state"]
    return {"id": exp_id, "status": exp["status"], "updated_at": exp["updated_at"],
            "execution": st.get("execution"), "error": st.get("error"),
            "runs": [{k: r[k] for k in ("run_id", "status")} for r in repo.list_runs(exp_id)]}


@router.get("/{exp_id}/results")
async def get_results(exp_id: str, request: Request):
    repo, _ = _deps(request)
    exp = _require(repo, exp_id)
    st = exp["state"]
    return {"id": exp_id, "status": exp["status"], "seed": (st.get("experiment_plan") or {}).get("seed"),
            "dataset_version": "rag-eval-v1", "runs": repo.get_results(exp_id, include_raw=True),
            "statistics": st.get("statistics"), "analysis": st.get("analysis")}


@router.post("/{exp_id}/next", status_code=201)
async def run_next(exp_id: str, request: Request):
    repo, _ = _deps(request)
    exp = _require(repo, exp_id)
    if exp["status"] != ExperimentStatus.COMPLETED.value:
        raise HTTPException(409, "the next experiment can only be created from a completed experiment")
    parent = repo.get_state(exp_id)
    if not parent.next_experiment:
        raise HTTPException(409, "this experiment has no proposed next experiment")
    # Guardrail: one follow-up per proposal (double-clicks must not launch a second paid run).
    existing = [c for c in repo.children(exp_id) if c["status"] not in ("FAILED", "CANCELLED")]
    if existing:
        raise HTTPException(409, {"message": f"The next experiment already exists as {existing[0]['id']}.",
                                  "experiment_id": existing[0]["id"]})
    mode = _ensure_reasoning_available(request)
    state = ExperimentState(research_question=parent.next_experiment.research_question, llm_mode=mode,
                            seed_proposal=parent.next_experiment, use_research=parent.use_research)
    return _launch(request, state, parent_id=exp_id)


@router.post("/{exp_id}/cancel")
async def cancel(exp_id: str, request: Request):
    repo, orch = _deps(request)
    exp = _require(repo, exp_id)
    if ExperimentStatus(exp["status"]).terminal:
        raise HTTPException(409, f"experiment already {exp['status']}")
    await orch.cancel(exp_id)
    return repo.get_experiment(exp_id)


@router.get("/{exp_id}/events")
async def stream_events(exp_id: str, request: Request, after: int = 0):
    """Server-sent events: replays persisted events, then streams live ones."""
    repo, _ = _deps(request)
    _require(repo, exp_id)
    bus = request.app.state.bus
    last_header = request.headers.get("last-event-id")
    after = max(after, int(last_header) if last_header and last_header.isdigit() else 0)

    async def gen():
        queue = bus.subscribe(exp_id)
        try:
            last = after
            for ev in repo.list_events(exp_id, after):
                last = ev.id or last
                yield _sse(ev.model_dump(mode="json"))
            if ExperimentStatus(repo.get_experiment(exp_id)["status"]).terminal:
                yield "event: end\ndata: {}\n\n"
                return
            while True:
                if await request.is_disconnected():
                    return
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if (payload.get("id") or 0) <= last:
                    continue
                last = payload["id"]
                yield _sse(payload)
                status = (payload.get("data") or {}).get("status")
                if payload.get("event_type") == "status" and status in ("COMPLETED", "FAILED", "CANCELLED"):
                    yield "event: end\ndata: {}\n\n"
                    return
        finally:
            bus.unsubscribe(exp_id, queue)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _sse(payload: dict) -> str:
    return f"id: {payload.get('id')}\nevent: agent\ndata: {json.dumps(payload, default=str, ensure_ascii=False)}\n\n"
