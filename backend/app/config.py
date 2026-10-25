"""Runtime configuration (environment variables / .env)."""

from __future__ import annotations

import shutil
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
RUNTIME_DIR = Path(__file__).resolve().parent / "execution" / "runtime"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR.parent / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Nebius Token Factory (OpenAI-compatible) running NVIDIA Nemotron ---------------
    nebius_api_key: str = ""
    nebius_base_url: str = "https://api.tokenfactory.nebius.com/v1/"
    # Stronger model: hypothesis, experiment design, code generation, analysis.
    nebius_model: str = ""
    # Smaller/faster model: question parsing, research summarisation. Falls back to NEBIUS_MODEL.
    nebius_fast_model: str = ""
    llm_timeout_seconds: float = 180.0
    llm_max_retries: int = 2
    # When no API key is configured, run with the deterministic offline planner instead of
    # refusing. The UI and /health label this loudly — Nemotron is NOT used in that mode.
    allow_offline_fallback: bool = True
    # Replay identical Nemotron requests from a local cache (saves Token Factory usage when
    # re-running the same experiment, e.g. demo rehearsals). Cached calls are labelled in the UI.
    llm_cache: bool = True
    llm_cache_dir: Path = BACKEND_DIR / ".llm_cache"
    # Usage guardrails (protect limited/trial plans). 0 disables a limit.
    llm_daily_token_budget: int = 300_000
    llm_max_calls_per_experiment: int = 20
    max_concurrent_experiments: int = 2
    experiment_rate_limit_per_minute: int = 6

    # --- Tavily (optional research discovery) -------------------------------------------
    tavily_api_key: str = ""
    tavily_max_results: int = 5

    # --- Storage ---------------------------------------------------------------------------
    database_url: str = "sqlite:///./experimentos.db"
    dataset_path: Path = BACKEND_DIR / "data" / "rag_eval.json"
    work_root: Path = BACKEND_DIR / ".work"

    # --- Execution ------------------------------------------------------------------------
    execution_mode: Literal["local", "nebius"] = "local"
    execution_timeout_seconds: int = 240
    execution_memory_mb: int = 1024
    execution_max_output_bytes: int = 2_000_000
    max_runs_per_experiment: int = 12
    max_attempts: int = 3

    # Nebius AI Cloud — Serverless AI Jobs (EXECUTION_MODE=nebius)
    nebius_cli: str = "nebius"
    nebius_project_id: str = ""
    nebius_job_image: str = ""
    nebius_job_platform: str = "cpu-d3"
    nebius_job_preset: str = "4vcpu-16gb"
    nebius_job_timeout: str = "1h"
    nebius_job_fallback_local: bool = True

    # --- API ---------------------------------------------------------------------------------
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    # Optional regex for origins, e.g. https://experimentos.*\.vercel\.app (covers Vercel preview URLs)
    cors_origin_regex: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        """Origins from CORS_ORIGINS. Bare hostnames (as Render's blueprint provides) get https://."""
        out = []
        for o in (x.strip().rstrip("/") for x in self.cors_origins.split(",")):
            if o:
                out.append(o if "://" in o else f"https://{o}")
        return out

    @property
    def nebius_configured(self) -> bool:
        return bool(self.nebius_api_key and self.nebius_model)

    @property
    def reasoning_model(self) -> str:
        return self.nebius_model

    @property
    def fast_model(self) -> str:
        return self.nebius_fast_model or self.nebius_model

    @property
    def tavily_configured(self) -> bool:
        return bool(self.tavily_api_key)

    @property
    def sqlite_path(self) -> str:
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            raise ValueError("Only sqlite:/// DATABASE_URLs are supported in this MVP")
        path = self.database_url[len(prefix):]
        if path == ":memory:":
            return path
        p = Path(path)
        return str(p if p.is_absolute() else (BACKEND_DIR / p).resolve())

    def nebius_jobs_ready(self) -> tuple[bool, str]:
        if not self.nebius_job_image:
            return False, "NEBIUS_JOB_IMAGE is not set"
        if not shutil.which(self.nebius_cli):
            return False, f"Nebius CLI '{self.nebius_cli}' not found on PATH"
        return True, "ready"

    def configuration_help(self) -> str:
        return (
            "Nemotron is not configured. Set NEBIUS_API_KEY and NEBIUS_MODEL (e.g. an NVIDIA "
            "Nemotron model ID copied from the Nebius Token Factory model catalog) in .env, "
            "then restart the backend. See README → 'Environment Variables'."
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
