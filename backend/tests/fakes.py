"""Scripted stand-in for Nemotron. Tests never need a live Nebius API key."""

from __future__ import annotations

import copy
from typing import Any

from app.llm.nebius_client import LLMCall, extract_code

UNDERSTAND = {"experiment_family": "retrieval_depth", "independent_variable": "retrieval_k",
              "dependent_variable": "accuracy", "summary": "Effect of retrieval depth on accuracy", "in_scope": True}

HYPOTHESIS = {
    "statement": "Increasing retrieval_k from 3 to 10 will improve answer accuracy on rag-eval-v1, "
                 "while increasing it beyond 10 will produce diminishing returns.",
    "independent_variable": "retrieval_k", "dependent_variable": "accuracy",
    "expected_direction": "non_monotonic",
    "expected_relationship": "accuracy rises then plateaus", "rationale": "more evidence, more distractors",
}

VAGUE_HYPOTHESIS = {**HYPOTHESIS, "statement": "RAG is better with more context in some way, it depends."}

PLAN = {
    "hypothesis": HYPOTHESIS["statement"],
    "objective": "Measure the effect of retrieval depth on accuracy",
    "independent_variables": [{"name": "retrieval_k", "description": "depth", "values": [3, 10, 20]}],
    "dependent_variables": ["accuracy", "retrieval_recall"],
    "control_variables": ["chunk_size=128", "retriever=bm25"],
    "baseline": {"run_id": "k3", "description": "k=3"},
    "configurations": [
        {"run_id": "k3", "label": "k=3", "params": {"retrieval_k": 3}, "is_baseline": True},
        {"run_id": "k10", "label": "k=10", "params": {"retrieval_k": 10}, "is_baseline": False},
        {"run_id": "k20", "label": "k=20", "params": {"retrieval_k": 20}, "is_baseline": False},
    ],
    "dataset": {"id": "rag-eval-v1"},
    "metrics": [{"name": "accuracy", "goal": "maximize"}],
    "primary_metric": "accuracy",
    "success_criteria": "accuracy at k=10 exceeds k=3 with McNemar p < 0.05",
    "seed": 42,
}

CODE = '''```python
from experimentos_sdk import set_seed, plan_evaluations, run_configuration, finish
set_seed(42)
RUNS = [("k3", {"retrieval_k": 3}), ("k10", {"retrieval_k": 10}), ("k20", {"retrieval_k": 20})]
plan_evaluations(len(RUNS))
for run_id, params in RUNS:
    run_configuration(run_id, **params)
finish()
```'''

UNSAFE_CODE = '''```python
import os
os.system("echo hi")
```'''

ANALYSIS = {
    "summary": "Accuracy did not improve consistently as retrieval depth increased.",
    "hypothesis_status": "INCONCLUSIVE",
    "status_rationale": "Differences versus the baseline were not significant.",
    "key_findings": [{"statement": "Deeper retrieval raised recall without a matching accuracy gain.",
                      "evidence": ["k3", "k20"]}],
    "evidence": ["k3", "k10", "k20"],
    "limitations": ["Small synthetic dataset."],
    "conclusion": "More retrieved context alone is not sufficient.",
}

UNGROUNDED_ANALYSIS = {**ANALYSIS, "summary": "Accuracy reached 99.7% at k=10, a 41.3 point gain."}

NEXT = {
    "title": "Reranking deep candidate lists",
    "research_question": "Does reranking 20 retrieved chunks improve accuracy over k=10?",
    "hypothesis": "Reranking 20 retrieved chunks to the top 5 will increase accuracy over a k=10 baseline.",
    "rationale": "Recall saturated but accuracy did not; distractors are the likely cause.",
    "varied_parameter": "reranker",
    "baseline": {"label": "k=10", "params": {"retrieval_k": 10}},
    "treatment": {"label": "k=20 + rerank top 5", "params": {"retrieval_k": 20, "reranker": "cross_lite", "rerank_top_n": 5}},
    "configurations": [
        {"run_id": "k10", "label": "k=10", "params": {"retrieval_k": 10}, "is_baseline": True},
        {"run_id": "k20_rr5", "label": "k=20 + rerank top 5",
         "params": {"retrieval_k": 20, "reranker": "cross_lite", "rerank_top_n": 5}, "is_baseline": False},
    ],
}


class FakeLLM:
    """Returns scripted responses per task; the last scripted response repeats."""

    provider = "fake"

    def __init__(self, script: dict[str, list[Any]] | None = None):
        self.script = {
            "understand_question": [UNDERSTAND],
            "summarize_research": [{"known_findings": ["More context can add noise."], "research_gap": "where it plateaus",
                                    "testable_locally": "vary retrieval_k"}],
            "create_hypothesis": [HYPOTHESIS],
            "design_experiment": [PLAN],
            "generate_experiment_code": [CODE],
            "analyze_results": [ANALYSIS],
            "create_next_experiment": [NEXT],
        }
        self.script.update(script or {})
        self.calls: list[str] = []
        self.on_call = None

    def with_hook(self, on_call):
        self.on_call = on_call
        return self

    def model_for(self, tier: str) -> str:
        return f"fake-nemotron-{tier}"

    def _next(self, task: str) -> Any:
        self.calls.append(task)
        seq = self.script[task]
        item = seq.pop(0) if len(seq) > 1 else seq[0]
        if isinstance(item, Exception):
            raise item
        return copy.deepcopy(item)

    async def _report(self, task: str, tier: str) -> None:
        if self.on_call:
            await self.on_call(LLMCall(task=task, tier=tier, model=self.model_for(tier), latency_s=0.01,
                                       prompt_tokens=100, completion_tokens=50))

    async def complete_json(self, *, task, system, user, tier="reasoning", temperature=0.1, max_tokens=4096):
        await self._report(task, tier)
        return self._next(task)

    async def complete_text(self, *, task, system, user, tier="reasoning", temperature=0.2, max_tokens=4096):
        await self._report(task, tier)
        out = self._next(task)
        return out if isinstance(out, str) else str(out)


__all__ = ["FakeLLM", "extract_code"]
