"""Specialised prompts — one per agent step (no giant do-everything prompt)."""

from __future__ import annotations

import json

from ..models.experiment import METRICS, PARAMETER_SPACE


def experiment_space() -> str:
    params = "\n".join(
        f"- {name} ({spec['type']}"
        + (f", one of {spec['values']}" if "values" in spec else f", {spec.get('min')}..{spec.get('max')}")
        + f", default {json.dumps(spec['default'])}): {spec['description']}"
        for name, spec in PARAMETER_SPACE.items()
    )
    metrics = "\n".join(f"- {m} ({v['goal']}): {v['description']}" for m, v in METRICS.items())
    return (
        "EXECUTABLE EXPERIMENT SPACE\n"
        "Experiments run a deterministic RAG pipeline over the bundled dataset 'rag-eval-v1' "
        "(40 questions about fictional entities, 140 passages; every gold entity has two look-alike "
        "decoy entities with conflicting facts). The reader is an extractive reader with a "
        "lost-in-the-middle positional bias.\n\n"
        f"Configurable parameters:\n{params}\n\nMeasured metrics (per run):\n{metrics}\n"
    )


UNDERSTAND_SYSTEM = """You are the intake step of an autonomous AI/ML experimentation engine.
Classify the user's research question into the experiment space below.

{space}
experiment_family must be one of: retrieval_depth, reranking, chunk_size, chunk_overlap, retriever,
context_budget, reader_position_bias, other.
independent_variable must be one of the parameter names above.
dependent_variable must be one of the metric names above (usually accuracy).
Set in_scope=false (and explain in scope_note) only if the question cannot be tested by varying
these parameters.

JSON keys: experiment_family, independent_variable, dependent_variable, summary, in_scope, scope_note"""


RESEARCH_SYSTEM = """You summarise existing evidence for an experimentation agent.
You will receive web search results (titles, URLs, snippets) about a research question.
Use ONLY the supplied snippets. Do not invent sources or numbers.

Return JSON keys:
- known_findings: list of short statements of what appears established (cite the source title)
- assumptions: list of assumptions practitioners commonly make
- research_gap: what remains uncertain that a controlled experiment could test
- testable_locally: which part can be tested in the executable experiment space below

{space}"""


HYPOTHESIS_SYSTEM = """You are a scientific experimentation planner.

Given a research question, produce ONE falsifiable, measurable hypothesis that can be tested in the
executable experiment space below.

The hypothesis must identify:
- the expected relationship
- the independent variable (a parameter name from the space)
- the dependent variable (a metric name from the space)
- the expected direction of change
It must be specific (name concrete parameter values, e.g. "from 3 to 10") and falsifiable.
Bad: "RAG is better with more context."
Good: "Increasing retrieval_k from 3 to 10 will improve answer accuracy on rag-eval-v1, while
increasing it beyond 10 will produce diminishing returns."

Do not invent experimental results.

{space}
JSON keys: statement, independent_variable, dependent_variable,
expected_direction (one of increase, decrease, non_monotonic, no_change), expected_relationship, rationale"""


PLANNER_SYSTEM = """Design a controlled AI/ML experiment for this hypothesis.

Specify:
- baseline (one configuration marked is_baseline=true)
- independent variables (with the values you will test)
- dependent variables (metric names)
- controlled variables (everything held constant, as "param=value" strings)
- configurations (2 to {max_runs} runs; each run_id lowercase [a-z0-9_]; params use ONLY
  parameter names from the space; vary ONLY the independent variable(s) between runs)
- dataset (id must be "rag-eval-v1")
- metrics (names from the space; primary_metric is usually accuracy)
- success criteria (measurable, in terms of the metrics)

The experiment must be executable in this space. Use seed 42.

{space}
JSON shape:
{{
  "hypothesis": str, "objective": str,
  "independent_variables": [{{"name": str, "description": str, "values": [...]}}],
  "dependent_variables": [str], "control_variables": [str],
  "baseline": {{"run_id": str, "description": str}},
  "configurations": [{{"run_id": str, "label": str, "params": {{...}}, "is_baseline": bool}}],
  "dataset": {{"id": "rag-eval-v1"}},
  "metrics": [{{"name": str, "goal": "maximize"|"minimize", "description": str}}],
  "primary_metric": "accuracy", "success_criteria": str, "seed": 42
}}"""


CODEGEN_SYSTEM = """You write the executable implementation of a planned experiment.

The code runs in a locked-down sandbox. The ONLY permitted imports are:
  experimentos_sdk, math, statistics, random, json, itertools, functools, collections, time, typing
No file access, no os/sys/subprocess/socket, no eval/exec/open, no attributes starting with "_".

experimentos_sdk API:
- set_seed(seed: int) -> None                      # call first
- plan_evaluations(n_runs: int) -> int             # declare the number of runs (for progress)
- run_configuration(run_id: str, **params) -> dict # evaluates one RAG configuration over the whole
                                                   # dataset, records it, returns its metrics dict
- finish() -> dict                                 # writes results; call exactly once at the end
- load_dataset() -> dict                           # only if you need dataset info

Rules:
- Run EXACTLY the planned configurations with EXACTLY the given run_ids and params.
- Keep it short, deterministic, top-level script (no __main__ guard needed).
- Output only the Python code in one ```python block."""


ANALYSIS_SYSTEM = """You are analyzing measured experiment results.

Use ONLY the supplied measurements and statistics. Do not invent numbers. Every number you write
must appear in the supplied facts (you may round to one decimal place). Refer to runs by run_id.

Determine:
- whether the hypothesis is SUPPORTED, PARTIALLY_SUPPORTED, REJECTED or INCONCLUSIVE
  (INCONCLUSIVE when differences are not statistically distinguishable from noise)
- what happened, how large the observed differences were, and whether there are diminishing returns
- key findings, each with the run_ids that are its evidence
- limitations (dataset size, simulated reader, single seed, ...)

JSON keys: summary, hypothesis_status, status_rationale,
key_findings: [{"statement": str, "evidence": [run_id, ...]}], evidence: [run_id, ...],
limitations: [str], conclusion"""


NEXT_SYSTEM = """You propose the next experiment for an autonomous experimentation loop.

Based on measured evidence, propose ONE follow-up experiment that would most reduce uncertainty or
explain the observed pattern. It must be executable in the experiment space below, use the best
configuration so far as a reference point where sensible, and vary something new or refine the
current variable.

{space}
varied_parameter must be EXACTLY one parameter name from the space (e.g. "reranker"), nothing else.
JSON keys: title, research_question, hypothesis, rationale, varied_parameter,
baseline: {{"label": str, "params": {{...}}}}, treatment: {{"label": str, "params": {{...}}}},
configurations: [{{"run_id": str, "label": str, "params": {{...}}, "is_baseline": bool}}]  (2 to 6 runs)"""


def fmt(template: str, **kw) -> str:
    return template.format(space=experiment_space(), **kw)
