"""The Experiment Agent: one explicit state machine that closes the research loop.

    question → hypothesis → design → validate → code → submit → run → measure
             → statistics → analysis → conclusion → next experiment ↺

Every state transition, tool call, LLM call and measurement is persisted as an
agent event and streamed to the UI over SSE — the timeline is never simulated.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import Settings
from ..evaluation.metrics import ResultParseError, parse_results
from ..evaluation.statistics import compute_statistics
from ..execution.runner import ExecutionOutcome, Executor
from ..llm.nebius_client import LLMCall, LLMClient
from ..llm.usage import LLMBudgetExceeded
from ..models.agent import AgentEvent, ExperimentState
from ..models.experiment import ExperimentStatus, check_transition
from ..research.tavily import TavilyClient, search_research
from ..storage.repositories import Repository
from . import offline
from .analyzer import analyze_results
from .code_generator import ExperimentCodeGenerator, validate_code
from .context import AgentContext
from .hypothesis import create_hypothesis, understand_question
from .next_experiment import create_next_experiment
from .planner import design_experiment, validate_experiment

log = logging.getLogger("experimentos.agent")
S = ExperimentStatus

STAGES = ["understand", "research", "hypothesis", "design", "validate", "codegen", "submit", "run",
          "analyze", "next"]


class AgentFailure(Exception):
    """A failure the agent could not recover from; message is user-facing."""


class EventBus:
    """In-process pub/sub for live SSE streams (events are also persisted)."""

    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, exp_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self._subs[exp_id].add(q)
        return q

    def unsubscribe(self, exp_id: str, q: asyncio.Queue) -> None:
        self._subs[exp_id].discard(q)

    def publish(self, exp_id: str, payload: dict[str, Any]) -> None:
        for q in list(self._subs.get(exp_id, ())):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass


class ExperimentOrchestrator:
    def __init__(self, settings: Settings, repo: Repository, bus: EventBus, llm: LLMClient | None,
                 tavily: TavilyClient | None, executor: Executor, n_questions: int):
        self.settings = settings
        self.repo = repo
        self.bus = bus
        self.llm = llm
        self.tavily = tavily
        self.executor = executor
        self.n_questions = n_questions
        self.codegen = ExperimentCodeGenerator()
        self.tasks: dict[str, asyncio.Task] = {}

    # ------------------------------------------------------------------ lifecycle -----
    def start(self, exp_id: str) -> asyncio.Task:
        task = asyncio.create_task(self.run(exp_id), name=f"experiment-{exp_id}")
        self.tasks[exp_id] = task
        task.add_done_callback(lambda _t: self.tasks.pop(exp_id, None))
        return task

    async def cancel(self, exp_id: str) -> bool:
        task = self.tasks.get(exp_id)
        if not task:
            return False
        task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=5)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
            pass
        return True

    async def shutdown(self) -> None:
        for exp_id in list(self.tasks):
            await self.cancel(exp_id)

    # ------------------------------------------------------------------ events -------
    async def emit(self, exp_id: str, event_type: str, message: str, **data: Any) -> None:
        stage = data.pop("stage", None)
        tool = data.pop("tool", None)
        ev = AgentEvent(experiment_id=exp_id, event_type=event_type, message=message, stage=stage, tool=tool,
                        data=data, timestamp=datetime.now(timezone.utc))
        ev = self.repo.add_event(ev)
        self.bus.publish(exp_id, ev.model_dump(mode="json"))

    async def _stage(self, exp_id: str, stage: str, state: str, message: str, **data: Any) -> None:
        await self.emit(exp_id, "stage", message, stage=stage, state=state, **data)

    async def _transition(self, exp_id: str, current: list[ExperimentStatus], new: ExperimentStatus) -> None:
        check_transition(current[0], new)
        self.repo.set_status(exp_id, new)
        await self.emit(exp_id, "status", f"Status → {new.value}", status=new.value, previous=current[0].value)
        current[0] = new

    class _Tool:
        def __init__(self, orch: "ExperimentOrchestrator", exp_id: str, name: str, stage: str, message: str):
            self.o, self.exp_id, self.name, self.stage, self.message = orch, exp_id, name, stage, message

        async def __aenter__(self):
            self.t0 = time.perf_counter()
            await self.o.emit(self.exp_id, "tool_call", self.message, tool=self.name, stage=self.stage)
            return self

        async def __aexit__(self, exc_type, exc, tb):
            dt = round(time.perf_counter() - self.t0, 2)
            if exc_type is None:
                await self.o.emit(self.exp_id, "tool_result", f"{self.name} completed in {dt}s",
                                  tool=self.name, stage=self.stage, duration_s=dt, ok=True)
            elif not issubclass(exc_type, asyncio.CancelledError):
                await self.o.emit(self.exp_id, "tool_result", f"{self.name} failed: {exc}",
                                  tool=self.name, stage=self.stage, duration_s=dt, ok=False)
            return False

    async def _guarded(self, exp_id: str, ctx: AgentContext, fn, *args, **kwargs):
        """Run a Nemotron-backed step; if a usage guardrail trips, finish on the rule-based path.

        Measurements already paid for are never thrown away because the token budget ran out.
        """
        try:
            return await fn(ctx, *args, **kwargs)
        except LLMBudgetExceeded as e:
            if ctx.offline:
                raise
            ctx.llm = None
            await self.emit(exp_id, "warning", f"{e} Continuing with the rule-based planner — Nemotron is "
                            "disabled for the rest of this experiment.", guardrail="llm_budget")
            return await fn(ctx, *args, **kwargs)

    def tool(self, exp_id: str, name: str, stage: str, message: str) -> "_Tool":
        return self._Tool(self, exp_id, name, stage, message)

    # ------------------------------------------------------------------ main loop ----
    async def run(self, exp_id: str) -> None:
        state = self.repo.get_state(exp_id)
        current = [S(self.repo.get_experiment(exp_id)["status"])]

        async def on_llm_call(call: LLMCall) -> None:
            tokens = (call.prompt_tokens or 0) + (call.completion_tokens or 0)
            cached = bool(call.extra.get("cached"))
            state.models[call.tier] = call.model
            if not call.ok:
                msg = f"Nemotron call failed · {call.task} · {call.error}"
            elif cached:
                msg = f"Nemotron (cached replay, no tokens used) · {call.task} · {call.model}"
            else:
                msg = (f"Nemotron · {call.task} · {call.model} · {call.latency_s:.1f}s"
                       + (f" · {tokens:,} tokens" if tokens else ""))
            await self.emit(exp_id, "llm_call", msg, task=call.task, tier=call.tier, model=call.model,
                            latency_s=round(call.latency_s, 2), prompt_tokens=call.prompt_tokens,
                            completion_tokens=call.completion_tokens, ok=call.ok, cached=cached,
                            provider="Nebius Token Factory")

        llm = self.llm
        if llm is not None and hasattr(llm, "with_hook"):
            llm = llm.with_hook(on_llm_call)  # type: ignore[union-attr]
        ctx = AgentContext(llm=llm, max_attempts=self.settings.max_attempts,
                           emit=lambda t, m, **d: self.emit(exp_id, t, m, **d))
        try:
            await self._pipeline(exp_id, state, current, ctx)
        except asyncio.CancelledError:
            state.error = "Cancelled by user."
            self.repo.save_state(exp_id, state)
            if not current[0].terminal:
                self.repo.set_status(exp_id, S.CANCELLED)
                await self.emit(exp_id, "status", "Experiment cancelled.", status=S.CANCELLED.value)
        except AgentFailure as e:
            await self._fail(exp_id, state, current, str(e))
        except Exception as e:  # noqa: BLE001 — surface every failure to the user
            log.exception("experiment %s crashed", exp_id)
            await self._fail(exp_id, state, current, f"Unexpected error: {type(e).__name__}: {e}")

    async def _fail(self, exp_id: str, state: ExperimentState, current: list[ExperimentStatus], msg: str) -> None:
        state.error = msg
        self.repo.save_state(exp_id, state)
        await self.emit(exp_id, "error", msg)
        if not current[0].terminal:
            await self._transition(exp_id, current, S.FAILED)

    async def _pipeline(self, exp_id: str, state: ExperimentState, current: list[ExperimentStatus],
                        ctx: AgentContext) -> None:
        q = state.research_question
        save = lambda **cols: self.repo.save_state(exp_id, state, **cols)  # noqa: E731
        mode = "Nemotron via Nebius Token Factory" if not ctx.offline else "OFFLINE MODE (Nemotron not configured)"
        await self.emit(exp_id, "log", f"Question received · reasoning: {mode} · execution: {self.executor.name}")

        # ---------------------------------------------------------------- PLANNING
        await self._transition(exp_id, current, S.PLANNING)

        await self._stage(exp_id, "understand", "started", "Understanding question")
        async with self.tool(exp_id, "understand_question", "understand", "Parsing the research question"):
            state.understanding = await self._guarded(exp_id, ctx, understand_question, q)
        if not state.understanding.in_scope:
            raise AgentFailure("This question is outside the executable experiment space. "
                               + (state.understanding.scope_note or ""))
        fam = state.understanding.experiment_family
        title = (state.seed_proposal.title if state.seed_proposal
                 else offline.FAMILIES.get(fam, {}).get("title") or state.understanding.summary[:80])
        save(title=title)
        await self._stage(exp_id, "understand", "completed",
                          f"Question understood: vary {state.understanding.independent_variable}, "
                          f"measure {state.understanding.dependent_variable}", family=fam)

        await self._stage(exp_id, "research", "started", "Searching existing evidence")
        tavily = self.tavily if state.use_research else None
        async with self.tool(exp_id, "search_research", "research",
                             "Searching existing evidence with Tavily" if tavily else "Checking existing evidence"):
            state.research_context = await self._guarded(exp_id, ctx, search_research, tavily, q)
        if state.research_context.sources:
            self.repo.save_sources(exp_id, state.research_context.sources)
        save()
        await self._stage(exp_id, "research", "completed" if state.research_context.searched else "skipped",
                          f"{len(state.research_context.sources)} sources reviewed" if state.research_context.searched
                          else state.research_context.note)

        await self._stage(exp_id, "hypothesis", "started", "Generating hypothesis")
        async with self.tool(exp_id, "create_hypothesis", "hypothesis", "Forming a falsifiable hypothesis"):
            try:
                state.hypothesis = await self._guarded(exp_id, ctx, create_hypothesis, q, state.understanding, state.research_context,
                                                           state.seed_proposal)
            except Exception as e:
                raise AgentFailure(str(e)) from e
        save()
        await self._stage(exp_id, "hypothesis", "completed", state.hypothesis.statement)

        await self._stage(exp_id, "design", "started", "Designing experiment")
        feedback: list[str] | None = None
        for attempt in range(1, self.settings.max_attempts + 1):
            async with self.tool(exp_id, "design_experiment", "design",
                                 "Designing a controlled experiment" if attempt == 1 else "Revising experiment design"):
                try:
                    state.experiment_plan = await self._guarded(
                        exp_id, ctx, design_experiment, q, state.hypothesis, state.understanding, state.research_context, state.seed_proposal,
                        revision_feedback=feedback, previous_plan=state.experiment_plan,
                        max_runs=self.settings.max_runs_per_experiment)
                except Exception as e:
                    raise AgentFailure(f"Experiment design failed: {e}") from e
            save()
            await self._stage(exp_id, "design", "completed",
                              f"{len(state.experiment_plan.configurations)} configurations, baseline "
                              f"{state.experiment_plan.baseline.run_id}")

            # ------------------------------------------------------------ VALIDATING
            await self._transition(exp_id, current, S.VALIDATING)
            await self._stage(exp_id, "validate", "started", "Validating experiment")
            async with self.tool(exp_id, "validate_experiment", "validate", "Running 7 pre-execution checks"):
                state.validation_result = validate_experiment(state.experiment_plan, self.n_questions,
                                                              self.settings.max_runs_per_experiment,
                                                              hypothesis=state.hypothesis)
            save()
            if state.validation_result.passed:
                await self._stage(exp_id, "validate", "completed", "All 7 pre-execution checks passed")
                break
            feedback = state.validation_result.failures
            await self.emit(exp_id, "retry", f"Experiment invalid (attempt {attempt}/{self.settings.max_attempts}): "
                            + "; ".join(feedback), stage="validate", failures=feedback)
            if attempt == self.settings.max_attempts or ctx.offline:
                await self._stage(exp_id, "validate", "failed", "Validation failed")
                raise AgentFailure("Experiment could not be safely executed. Review experiment configuration. "
                                   + "; ".join(feedback))
            await self._transition(exp_id, current, S.PLANNING)
            await self._stage(exp_id, "design", "started", "Requesting plan revision from Nemotron")

        # ---------------------------------------------------------------- GENERATING_CODE
        await self._transition(exp_id, current, S.GENERATING_CODE)
        await self._stage(exp_id, "codegen", "started", "Generating code")
        async with self.tool(exp_id, "generate_experiment_code", "codegen", "Generating executable experiment code"):
            state.generated_code, state.code_source = await self._guarded(exp_id, ctx, self.codegen.generate, state.experiment_plan)
            state.code_validation = validate_code(state.generated_code)
        save()
        await self._stage(exp_id, "codegen", "completed",
                          f"Code generated by {'Nemotron' if state.code_source == 'nemotron' else 'template generator'}"
                          " · checks 8–9 passed", source=state.code_source)

        # ---------------------------------------------------------------- QUEUED / RUNNING
        results = None
        for attempt in range(1, self.settings.max_attempts + 1):
            outcome = await self._execute(exp_id, state, current, attempt)
            if outcome.ok:
                async with self.tool(exp_id, "get_experiment_results", "run", "Collecting measured results"):
                    try:
                        plan_cfgs = state.experiment_plan.configurations
                        results = parse_results(outcome.raw_results or {}, [c.run_id for c in plan_cfgs],
                                                {c.run_id: c.params for c in plan_cfgs})
                    except ResultParseError as e:
                        outcome.ok, outcome.error = False, f"Result validation failed: {e}"
            if outcome.ok and results is not None:
                break

            reason = outcome.error or "unknown error"
            state.execution.error = reason
            save()
            if attempt == self.settings.max_attempts:
                await self._stage(exp_id, "run", "failed", "Experiment execution failed")
                raise AgentFailure(f"Experiment could not be safely executed after {attempt} attempts. "
                                   f"Last error: {reason}. Review experiment configuration.")
            if outcome.timed_out or state.code_source == "template" or ctx.offline:
                action = "Retrying with the reference implementation" if not outcome.timed_out else \
                    "Reduce experiment size and retry: re-running with the reference implementation"
            else:
                action = "Requesting a corrected implementation from Nemotron"
            await self.emit(exp_id, "error", f"Experiment execution failed. Reason: {reason}. Action: {action}.",
                            stage="run", reason=reason, action=action, attempt=attempt)
            await self._transition(exp_id, current, S.GENERATING_CODE)
            await self._stage(exp_id, "codegen", "started", "Correcting experiment code")
            async with self.tool(exp_id, "generate_experiment_code", "codegen", action):
                if "Nemotron" in action:
                    state.generated_code, state.code_source = await self._guarded(
                        exp_id, ctx, self.codegen.generate, state.experiment_plan, feedback=[f"runtime failure: {reason}"],
                        previous_code=state.generated_code)
                else:
                    state.generated_code, state.code_source = self.codegen.template(state.experiment_plan), "template"
                state.code_validation = validate_code(state.generated_code)
            save()
            await self._stage(exp_id, "codegen", "completed", "Corrected code ready", source=state.code_source)

        assert results is not None
        self.repo.save_results(exp_id, results.runs)
        # Results, code and logs are persisted; the sandbox working files are no longer needed.
        shutil.rmtree(Path(self.settings.work_root) / exp_id, ignore_errors=True)
        await self._stage(exp_id, "run", "completed",
                          f"{sum(r.metrics.n_questions for r in results.runs)} evaluations complete",
                          duration_s=state.execution.duration_s)

        # ---------------------------------------------------------------- ANALYZING
        await self._transition(exp_id, current, S.ANALYZING)
        await self._stage(exp_id, "analyze", "started", "Analyzing results")
        async with self.tool(exp_id, "calculate_statistics", "analyze",
                             "Computing statistics in Python (CIs, paired tests, trends)"):
            state.statistics = compute_statistics(results, state.experiment_plan)
        save()
        async with self.tool(exp_id, "analyze_results", "analyze", "Interpreting the measured evidence"):
            state.analysis = await self._guarded(exp_id, ctx, analyze_results, q, state.hypothesis, state.experiment_plan, state.statistics)
        save()
        await self._stage(exp_id, "analyze", "completed",
                          f"Hypothesis {state.analysis.hypothesis_status.replace('_', ' ')}",
                          hypothesis_status=state.analysis.hypothesis_status)

        await self._stage(exp_id, "next", "started", "Generating next experiment")
        family = offline.IV_TO_FAMILY.get(state.experiment_plan.independent_variables[0].name, fam)
        async with self.tool(exp_id, "create_next_experiment", "next", "Proposing the next experiment from evidence"):
            state.next_experiment = await self._guarded(
                exp_id, ctx, create_next_experiment, family, q, state.hypothesis, state.experiment_plan, state.statistics, state.analysis)
            state.analysis.next_experiment = state.next_experiment
        save()
        await self._stage(exp_id, "next", "completed", f"Next: {state.next_experiment.title}")

        await self._transition(exp_id, current, S.COMPLETED)
        await self.emit(exp_id, "log", "Experiment complete — evidence recorded in the research trail.")

    async def _execute(self, exp_id: str, state: ExperimentState, current: list[ExperimentStatus],
                       attempt: int) -> ExecutionOutcome:
        plan = state.experiment_plan
        assert plan is not None and state.generated_code
        self.repo.replace_runs(exp_id, plan.configurations)
        await self._transition(exp_id, current, S.QUEUED)
        backend_label = ("Nebius AI Cloud Serverless Job" if self.executor.name == "nebius_job"
                         else "local sandbox")
        total = len(plan.configurations) * self.n_questions
        state.execution.attempts = attempt
        state.execution.total_evaluations = total
        state.execution.completed_evaluations = 0
        state.execution.error = None
        await self._stage(exp_id, "submit", "started", f"Submitting execution job ({backend_label})")
        async with self.tool(exp_id, "submit_experiment", "submit",
                             f"Submitting {len(plan.configurations)} runs to the {backend_label}"):
            await self._transition(exp_id, current, S.RUNNING)
        await self._stage(exp_id, "submit", "completed", f"Job submitted · attempt {attempt}", backend=self.executor.name)
        await self._stage(exp_id, "run", "started", f"Running {total} evaluations", total=total)

        async def on_event(ev: dict[str, Any]) -> None:
            t = ev.get("type")
            if t == "progress":
                done = int(ev.get("done") or 0)
                state.execution.completed_evaluations = done
                await self.emit(exp_id, "progress", f"{done}/{total} evaluations complete", stage="run",
                                done=done, total=total, run_id=ev.get("run_id"))
            elif t == "run_start":
                self.repo.set_run_status(exp_id, ev["run_id"], "RUNNING")
                await self.emit(exp_id, "log", f"Run {ev['run_id']} started", stage="run",
                                run_id=ev["run_id"], configuration=ev.get("configuration"))
            elif t == "run_complete":
                self.repo.set_run_status(exp_id, ev["run_id"], "COMPLETED")
                m = ev.get("metrics", {})
                await self.emit(exp_id, "log", f"Run {ev['run_id']} complete · accuracy {m.get('accuracy', 0) * 100:.1f}%"
                                f" · recall {m.get('retrieval_recall', 0) * 100:.1f}%", stage="run",
                                run_id=ev["run_id"], metrics=m)
            elif t == "sandbox":
                state.execution.sandbox = state.execution.sandbox or str(ev.get("limits", ""))
                await self.emit(exp_id, "log", f"Experiment started in sandbox · {ev.get('limits')}", stage="run")
            elif t == "job_submitted":
                state.execution.job_id = ev.get("job_id")
                await self.emit(exp_id, "log", f"Nebius job {ev.get('job_id')} created on {ev.get('platform')} "
                                f"({ev.get('preset')})", stage="submit", **ev)
            elif t == "job_state":
                async with self.tool(exp_id, "get_experiment_status", "run", f"Nebius job state: {ev.get('state')}"):
                    pass
            elif t == "backend_fallback":
                await self.emit(exp_id, "warning", f"Nebius job execution unavailable ({ev.get('reason')}); "
                                "falling back to the local sandbox.", stage="submit")
            elif t == "error":
                await self.emit(exp_id, "error", f"Experiment raised: {ev.get('error')}", stage="run")

        outcome = await self.executor.execute(experiment_id=exp_id, code=state.generated_code, attempt=attempt,
                                              on_event=on_event)
        state.execution.backend = "nebius_job" if outcome.backend == "nebius_job" else "local_sandbox"
        state.execution.duration_s = outcome.duration_s
        state.execution.job_id = outcome.job_id or state.execution.job_id
        state.execution.sandbox = outcome.sandbox or state.execution.sandbox
        state.execution.logs_tail = outcome.logs[-60:]
        self.repo.save_state(exp_id, state)
        if not outcome.ok:
            self.repo.reset_runs(exp_id)
        return outcome
