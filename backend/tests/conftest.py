from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

from .fakes import FakeLLM

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        work_root=tmp_path / "work",
        nebius_api_key="", nebius_model="", tavily_api_key="",
        execution_mode="local", execution_timeout_seconds=120,
    )


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


def make_client(settings: Settings, llm=None, executor=None) -> TestClient:
    return TestClient(create_app(settings, llm=llm, executor=executor, tavily=None))


def wait_terminal(client: TestClient, exp_id: str, timeout: float = 90.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = client.get(f"/experiments/{exp_id}/status").json()
        if st["status"] in TERMINAL:
            return client.get(f"/experiments/{exp_id}").json()
        time.sleep(0.2)
    raise AssertionError(f"experiment {exp_id} did not finish in {timeout}s")
