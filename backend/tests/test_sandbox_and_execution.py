import asyncio
import json

import pytest

from app.agent.code_generator import ExperimentCodeGenerator, validate_code
from app.execution.code_policy import check_code
from app.execution.nebius_jobs import NebiusJobExecutor, _find_state
from app.execution.runtime.experimentos_sdk.rag import RAGConfig, evaluate_rag
from app.execution.sandbox import LocalSandboxExecutor
from app.models.experiment import ExperimentPlan

from .fakes import PLAN


@pytest.mark.parametrize("code,needle", [
    ("import os\nos.system('x')\nfinish()\nrun_configuration('a')", "import of 'os'"),
    ("import subprocess", "subprocess"),
    ("x = ().__class__.__base__.__subclasses__()", "__class__"),
    ("open('/etc/passwd')", "open"),
    ("eval('1+1')", "eval"),
    ("from experimentos_sdk.runtime import _STATE", "experimentos_sdk.runtime"),
    ("from experimentos_sdk import _configure", "_configure"),
    ("getattr(object, 'x')", "getattr"),
    ("import json\njson.codecs.open('x')", "json.codecs"),
    ("from json import decoder", "json.decoder"),
    ("import experimentos_sdk\nexperimentos_sdk.runtime", "runtime"),
    ("x = 0\nwhile x < 10:\n    x += 1", "while-loops"),
])
def test_policy_rejects_dangerous_code(code, needle):
    r = check_code(code)
    assert not r.ok
    assert any(needle in v for v in r.violations) or needle in r.syntax_error


def test_policy_rejects_syntax_errors():
    report = validate_code("def broken(:\n")
    assert not report.passed
    assert report.checks[0].id == 8 and not report.checks[0].passed


def test_template_code_passes_policy():
    code = ExperimentCodeGenerator.template(ExperimentPlan.model_validate(PLAN))
    assert validate_code(code).passed


def test_rag_pipeline_is_deterministic(settings):
    data = json.loads(settings.dataset_path.read_text(encoding="utf-8"))
    a = evaluate_rag(data, RAGConfig(retrieval_k=5), limit=10)["metrics"]
    b = evaluate_rag(data, RAGConfig(retrieval_k=5), limit=10)["metrics"]
    assert {k: v for k, v in a.items() if k != "latency_ms"} == {k: v for k, v in b.items() if k != "latency_ms"}


def test_rag_config_validation():
    with pytest.raises(ValueError):
        RAGConfig(retrieval_k=0).validate()
    with pytest.raises(ValueError):
        RAGConfig(retriever="magic").validate()
    with pytest.raises(ValueError):
        RAGConfig(retrieval_k=5, reranker="cross_lite", rerank_top_n=9).validate()


async def _run(settings, code):
    events = []

    async def on_event(e):
        events.append(e)

    out = await LocalSandboxExecutor(settings).execute(experiment_id="exp_t", code=code, attempt=1, on_event=on_event)
    return out, events


async def test_sandbox_executes_generated_code(settings):
    code = ExperimentCodeGenerator.template(ExperimentPlan.model_validate(PLAN))
    out, events = await _run(settings, code)
    assert out.ok, out.error
    assert [r["run_id"] for r in out.raw_results["runs"]] == ["k3", "k10", "k20"]
    assert any(e["type"] == "progress" for e in events)
    assert out.raw_results["seed"] == 42


def test_runtime_layer_blocks_escape_even_without_static_policy(settings, tmp_path):
    """Defence in depth: run hostile code through the bootstrap directly, skipping the AST gate."""
    import subprocess
    import sys
    from app.execution.sandbox import BOOTSTRAP, sandbox_env
    code = tmp_path / "evil.py"
    target = str(tmp_path / "evil.py").replace("\\", "/")  # a file outside the sandbox workdir
    code.write_text(f"import json\nprint(json.codecs.open('{target}').read())\n", encoding="utf-8")
    out = subprocess.run([sys.executable, "-I", "-B", str(BOOTSTRAP), "--code", str(code),
                          "--workdir", str(tmp_path / "out"), "--dataset", str(settings.dataset_path)],
                         capture_output=True, text=True, env=sandbox_env(), timeout=60)
    assert "not permitted" in out.stdout and out.returncode != 0


async def test_sandbox_rejects_policy_violations_before_running(settings):
    out, _ = await _run(settings, "import os\nfrom experimentos_sdk import run_configuration, finish\n")
    assert not out.ok and "safety policy" in out.error


async def test_sandbox_timeout(settings):
    settings.execution_timeout_seconds = 2
    code = ("from experimentos_sdk import run_configuration, finish\nimport time\n"
            "for _ in range(10**9):\n    time.sleep(0.1)\nrun_configuration('a', retrieval_k=1)\nfinish()\n")
    out, _ = await _run(settings, code)
    assert not out.ok and out.timed_out


async def test_nebius_executor_falls_back_without_cli(settings):
    settings.execution_mode = "nebius"
    settings.nebius_job_image = ""
    code = ExperimentCodeGenerator.template(ExperimentPlan.model_validate(PLAN))
    events = []

    async def on_event(e):
        events.append(e)

    out = await NebiusJobExecutor(settings).execute(experiment_id="exp_n", code=code, attempt=1, on_event=on_event)
    assert out.ok
    assert events[0]["type"] == "backend_fallback"


def test_nebius_job_args(settings, tmp_path):
    settings.nebius_job_image = "cr.example/experimentos-runner:1"
    settings.nebius_project_id = "project-123"
    args = NebiusJobExecutor(settings).build_create_args("job-a", tmp_path / "e.py", "exp_1")
    assert args[:3] == ["ai", "job", "create"]
    assert "--inject-file" in args and "--async" in args
    assert args[args.index("--parent-id") + 1] == "project-123"
    assert _find_state({"status": {"state": "Running"}}) == "RUNNING"
