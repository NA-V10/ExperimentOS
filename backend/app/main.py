"""ExperimentOS API — FastAPI application factory."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .agent.orchestrator import EventBus, ExperimentOrchestrator
from .api import datasets, experiments, health
from .config import Settings, get_settings
from .evaluation.dataset import check_dataset
from .execution.runner import Executor, get_executor
from .llm.nebius_client import LLMClient, NebiusClient
from .llm.usage import UsageTracker
from .research.tavily import TavilyClient
from .storage.database import Database
from .storage.repositories import Repository

log = logging.getLogger("experimentos")

_UNSET = object()


def create_app(settings: Settings | None = None, llm: LLMClient | None | object = _UNSET,
               executor: Executor | None = None, tavily: TavilyClient | None | object = _UNSET) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        check_dataset(settings.dataset_path)  # refuse to start on a corrupted benchmark
        db = Database(settings.sqlite_path)
        repo = Repository(db)
        repo.register_dataset(settings.dataset_path)
        interrupted = repo.mark_interrupted()
        if interrupted:
            log.warning("marked %d interrupted experiments as FAILED", interrupted)

        usage = UsageTracker(settings.llm_cache_dir / "usage.json", settings.llm_daily_token_budget)
        if llm is _UNSET:
            client = NebiusClient(settings, usage=usage) if settings.nebius_configured else None
            if client is None:
                log.warning(settings.configuration_help()
                            + (" Running in OFFLINE MODE." if settings.allow_offline_fallback else ""))
        else:
            client = llm  # type: ignore[assignment]
        tv = (TavilyClient(settings.tavily_api_key, settings.tavily_max_results) if settings.tavily_configured
              else None) if tavily is _UNSET else tavily
        n_questions = len(json.loads(settings.dataset_path.read_text(encoding="utf-8"))["questions"])

        bus = EventBus()
        orch = ExperimentOrchestrator(settings, repo, bus, client, tv, executor or get_executor(settings), n_questions)
        app.state.settings, app.state.repo, app.state.bus = settings, repo, bus
        app.state.llm, app.state.orchestrator, app.state.usage = client, orch, usage
        try:
            yield
        finally:
            await orch.shutdown()
            if client is not None and hasattr(client, "aclose"):
                await client.aclose()
            db.close()

    app = FastAPI(title="ExperimentOS", version="1.0.0", lifespan=lifespan,
                  description="Autonomous experimentation engine: question → hypothesis → experiment → "
                              "evidence → conclusion → next experiment.")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_origin_regex=settings.cors_origin_regex or None,
        allow_methods=["*"], allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(experiments.router)
    app.include_router(datasets.router)
    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()
