"""ExperimentCodeGenerator: experiment plan -> executable, sandbox-safe Python."""

from __future__ import annotations

import json

from ..execution.code_policy import check_code
from ..llm.nebius_client import LLMError, extract_code
from ..models.experiment import ExperimentPlan, ValidationCheck, ValidationReport
from . import prompts
from .context import AgentContext


def validate_code(code: str) -> ValidationReport:
    """Validation checks 8 and 9."""
    r = check_code(code)
    missing = []
    if r.syntax_ok and not r.calls_run_configuration:
        missing.append("never calls run_configuration()")
    if r.syntax_ok and not r.calls_finish:
        missing.append("never calls finish()")
    return ValidationReport(checks=[
        ValidationCheck(id=8, name="Generated code is syntactically valid", passed=r.syntax_ok and not missing,
                        detail="parsed OK" if r.syntax_ok and not missing else (r.syntax_error or "; ".join(missing))),
        ValidationCheck(id=9, name="Only permitted libraries/tools", passed=r.syntax_ok and not r.violations,
                        detail="allow-listed imports and SDK calls only" if not r.violations else "; ".join(r.violations[:6])),
    ])


class ExperimentCodeGenerator:
    """Generates experiment code with Nemotron; falls back to a deterministic template."""

    @staticmethod
    def template(plan: ExperimentPlan) -> str:
        configs = ",\n".join(
            f"    ({json.dumps(c.run_id)}, {_py(c.params)})" for c in plan.configurations
        )
        controls = "\n".join(f"#   - {c}" for c in plan.control_variables) or "#   - (none listed)"
        return f'''"""
Experiment: {_doc(plan.objective)}
Hypothesis: {_doc(plan.hypothesis)}
Baseline:   {plan.baseline.run_id}
Controls:
{controls}
"""
from experimentos_sdk import finish, plan_evaluations, run_configuration, set_seed

set_seed({plan.seed})

# (run_id, RAG parameters) — only the independent variable(s) change between runs.
CONFIGURATIONS = [
{configs},
]

plan_evaluations(len(CONFIGURATIONS))
for run_id, params in CONFIGURATIONS:
    metrics = run_configuration(run_id, **params)
    print(run_id, "accuracy =", metrics["accuracy"])

finish()
'''

    async def generate(
        self, ctx: AgentContext, plan: ExperimentPlan, feedback: list[str] | None = None,
        previous_code: str | None = None,
    ) -> tuple[str, str]:
        """Return (code, source) where source is 'nemotron' or 'template'."""
        if ctx.offline:
            return self.template(plan), "template"

        spec = {
            "seed": plan.seed,
            "configurations": [{"run_id": c.run_id, "params": c.params} for c in plan.configurations],
            "baseline": plan.baseline.run_id,
            "objective": plan.objective,
        }
        user = "Implement this experiment plan:\n" + json.dumps(spec, indent=1)
        fb = list(feedback or [])
        for attempt in range(1, ctx.max_attempts + 1):
            prompt = user
            if fb:
                prompt += "\n\nYour previous code was rejected:\n- " + "\n- ".join(fb)
                if previous_code:
                    prompt += "\n\nPrevious code:\n```python\n" + previous_code + "```"
                prompt += "\nReturn corrected code."
            try:
                text = await ctx.llm.complete_text(
                    task="generate_experiment_code", tier="reasoning",
                    system=prompts.CODEGEN_SYSTEM, user=prompt, max_tokens=3072, temperature=0.1,
                )
            except LLMError as e:
                fb = [f"request failed: {e}"]
                await ctx.emit("retry", f"Code generation request failed (attempt {attempt}/{ctx.max_attempts}).",
                               stage="codegen")
                continue
            code = extract_code(text)
            report = validate_code(code)
            if report.passed:
                return code, "nemotron"
            fb, previous_code = report.failures, code
            await ctx.emit("retry", f"Generated experiment failed validation (attempt {attempt}/{ctx.max_attempts}). "
                           "Requesting correction...", stage="codegen", problems=fb)
        await ctx.emit("warning", "Nemotron code did not pass the safety policy after "
                       f"{ctx.max_attempts} attempts — using the deterministic template generator.", stage="codegen")
        return self.template(plan), "template"


def _py(value) -> str:
    """Render params as a Python literal (JSON scalars only, so repr is a valid literal)."""
    return repr(value)


def _doc(s: str) -> str:
    return s.replace('"""', "'''").replace("\n", " ")
