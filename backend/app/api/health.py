"""Health/configuration endpoint. Never exposes secrets."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request, deep: bool = False):
    s = request.app.state.settings
    llm = request.app.state.llm
    if s.execution_mode == "nebius":
        ready, detail = s.nebius_jobs_ready()
        execution = "ready" if ready else ("fallback_local" if s.nebius_job_fallback_local else "unavailable")
    else:
        execution, detail = "ready", "local sandbox"
    out = {
        "status": "ok",
        "nebius": "configured" if s.nebius_api_key else "not_configured",
        "model": "configured" if s.nebius_model else "not_configured",
        "models": {"reasoning": s.reasoning_model or None, "fast": s.fast_model or None},
        "llm_provider": "Nebius Token Factory",
        "llm_mode": "nemotron" if llm is not None else ("offline" if s.allow_offline_fallback else "unavailable"),
        "tavily": "configured" if s.tavily_configured else "not_configured",
        "execution": execution,
        "execution_mode": s.execution_mode,
        "execution_detail": detail,
        "dataset": next(iter(request.app.state.repo.list_datasets()), None),
    }
    usage = getattr(request.app.state, "usage", None)
    today = usage.today() if usage else {"tokens": 0, "calls": 0}
    out["guardrails"] = {
        "daily_token_budget": s.llm_daily_token_budget or None,
        "tokens_used_today": today["tokens"],
        "live_calls_today": today["calls"],
        "tokens_remaining_today": usage.remaining() if usage else None,
        "max_calls_per_experiment": s.llm_max_calls_per_experiment or None,
        "max_concurrent_experiments": s.max_concurrent_experiments or None,
        "experiment_rate_limit_per_minute": s.experiment_rate_limit_per_minute or None,
        "response_cache": s.llm_cache,
        "running_experiments": len(request.app.state.orchestrator.tasks),
    }
    if llm is None:
        out["help"] = s.configuration_help()
    if deep and llm is not None and hasattr(llm, "ping"):
        try:
            out["token_factory"] = await llm.ping()
        except Exception as e:  # noqa: BLE001
            out["token_factory"] = {"ok": False, "error": type(e).__name__}
    return out
