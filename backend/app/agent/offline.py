"""Deterministic offline reasoning — used ONLY when Nemotron is not configured.

This keeps the product usable for local development without an API key. Every
artifact produced here is labelled ``source="offline"`` and the UI shows an
"OFFLINE MODE — Nemotron not used" banner. Measurements, statistics and
execution are identical in both modes; only the language reasoning differs.
"""

from __future__ import annotations

import re
from typing import Any

from ..models.experiment import (
    BaselineSpec,
    ExperimentPlan,
    Hypothesis,
    MetricSpec,
    QuestionUnderstanding,
    RunConfiguration,
    Variable,
)
from ..models.results import Analysis, Finding, NextExperimentProposal, StatisticsReport

DEFAULTS = {"retrieval_k": 5, "chunk_size": 128, "chunk_overlap": 0, "retriever": "bm25",
            "reranker": "none", "rerank_top_n": None, "max_context_tokens": 4096,
            "reader_position_bias": 0.3}

FAMILIES: dict[str, dict[str, Any]] = {
    "retrieval_depth": {
        "iv": "retrieval_k",
        "keywords": [r"retriev\w* depth", r"top[- ]?k", r"number of (retrieved )?(documents|passages|chunks)",
                     r"retriev\w* (more|fewer)", r"\bk\b", r"retrieval_k", r"more documents"],
        "title": "RAG retrieval depth",
        "base": {},
        "runs": [("k3", "k=3", {"retrieval_k": 3}), ("k5", "k=5", {"retrieval_k": 5}),
                 ("k10", "k=10", {"retrieval_k": 10}), ("k20", "k=20", {"retrieval_k": 20})],
        "hypothesis": ("Increasing retrieval_k from 3 to 10 will improve answer accuracy on rag-eval-v1, "
                       "while increasing it beyond 10 will produce diminishing returns."),
        "direction": "non_monotonic",
        "relationship": "accuracy rises with retrieval depth up to k=10, then plateaus or declines",
    },
    "reranking": {
        "iv": "reranker",
        "keywords": [r"rerank", r"re-rank", r"cross[- ]?encoder"],
        "title": "Reranking vs retrieval depth",
        "base": {},
        "runs": [("k10_baseline", "k=10, no reranking", {"retrieval_k": 10}),
                 ("k20_baseline", "k=20, no reranking", {"retrieval_k": 20}),
                 ("k20_rerank_top10", "k=20 + rerank → top 10", {"retrieval_k": 20, "reranker": "cross_lite", "rerank_top_n": 10}),
                 ("k20_rerank_top5", "k=20 + rerank → top 5", {"retrieval_k": 20, "reranker": "cross_lite", "rerank_top_n": 5})],
        "hypothesis": ("Retrieving 20 chunks and reranking them down to the top 5 will improve answer accuracy "
                       "over a k=10 baseline without reranking, because reranking removes look-alike distractors."),
        "direction": "increase",
        "relationship": "reranking deep candidate lists increases accuracy versus plain top-k retrieval",
    },
    "chunk_overlap": {
        "iv": "chunk_overlap",
        "keywords": [r"overlap"],
        "title": "Chunk overlap",
        "base": {"chunk_size": 24, "retrieval_k": 5},
        "runs": [("ov0", "overlap 0", {"chunk_overlap": 0}), ("ov6", "overlap 6", {"chunk_overlap": 6}),
                 ("ov12", "overlap 12", {"chunk_overlap": 12})],
        "hypothesis": ("With 24-word chunks, increasing chunk_overlap from 0 to 12 words will increase answer "
                       "accuracy because fewer answer sentences are split across chunk boundaries."),
        "direction": "increase",
        "relationship": "overlap increases accuracy for small chunks",
    },
    "chunk_size": {
        "iv": "chunk_size",
        "keywords": [r"chunk", r"passage (size|length)", r"segment"],
        "title": "Chunk size",
        "base": {"retrieval_k": 5},
        "runs": [("cs16", "16 words", {"chunk_size": 16}), ("cs32", "32 words", {"chunk_size": 32}),
                 ("cs64", "64 words", {"chunk_size": 64}), ("cs128", "128 words", {"chunk_size": 128})],
        "hypothesis": ("Increasing chunk_size from 16 to 64 words will increase answer accuracy at fixed "
                       "retrieval_k=5, with little additional gain from 64 to 128 words."),
        "direction": "increase",
        "relationship": "larger chunks keep answers intact, improving accuracy until passages are whole",
    },
    "retriever": {
        "iv": "retriever",
        "keywords": [r"embedding", r"dense", r"hybrid", r"bm25", r"lexical", r"retriever", r"sparse"],
        "title": "Retriever / embedding configuration",
        "base": {"retrieval_k": 5},
        "runs": [("bm25", "BM25", {"retriever": "bm25"}), ("embedding", "char-trigram embedding", {"retriever": "embedding"}),
                 ("hybrid", "hybrid (RRF)", {"retriever": "hybrid"})],
        "hypothesis": ("Hybrid retrieval (BM25 + embedding fused with reciprocal-rank fusion) will achieve higher "
                       "answer accuracy than BM25 alone at retrieval_k=5."),
        "direction": "increase",
        "relationship": "hybrid retrieval improves accuracy over a single retriever",
    },
    "context_budget": {
        "iv": "max_context_tokens",
        "keywords": [r"context (window|size|budget|length)", r"token budget", r"max(imum)? context", r"long context"],
        "title": "Context budget",
        "base": {"retrieval_k": 20},
        "runs": [("ctx128", "128 tokens", {"max_context_tokens": 128}), ("ctx256", "256 tokens", {"max_context_tokens": 256}),
                 ("ctx512", "512 tokens", {"max_context_tokens": 512}), ("ctx1024", "1024 tokens", {"max_context_tokens": 1024})],
        "hypothesis": ("Increasing max_context_tokens from 128 to 512 will increase answer accuracy at retrieval_k=20, "
                       "with no further gain at 1024 tokens."),
        "direction": "non_monotonic",
        "relationship": "accuracy rises with context budget then saturates",
    },
    "reader_position_bias": {
        "iv": "reader_position_bias",
        "keywords": [r"lost in the middle", r"position", r"middle of the context", r"attention bias"],
        "title": "Lost-in-the-middle sensitivity",
        "base": {"retrieval_k": 20},
        "runs": [("bias0", "no position bias", {"reader_position_bias": 0.0}), ("bias15", "bias 0.15", {"reader_position_bias": 0.15}),
                 ("bias30", "bias 0.30", {"reader_position_bias": 0.3}), ("bias45", "bias 0.45", {"reader_position_bias": 0.45})],
        "hypothesis": ("Increasing the reader's positional bias from 0.0 to 0.45 will decrease answer accuracy at "
                       "retrieval_k=20, showing that long contexts hurt through lost-in-the-middle effects."),
        "direction": "decrease",
        "relationship": "stronger positional bias reduces accuracy with long contexts",
    },
}

CHAIN = {
    "retrieval_depth": "reranking",
    "reranking": "chunk_size",
    "chunk_size": "chunk_overlap",
    "chunk_overlap": "retriever",
    "retriever": "reader_position_bias",
    "reader_position_bias": "context_budget",
    "context_budget": "retrieval_depth",
}

IV_TO_FAMILY = {spec["iv"]: fam for fam, spec in FAMILIES.items()}
IV_TO_FAMILY["rerank_top_n"] = "reranking"


def classify(question: str) -> str | None:
    q = question.lower()
    for fam in ("reranking", "chunk_overlap", "chunk_size", "retriever", "context_budget",
                "reader_position_bias", "retrieval_depth"):
        if any(re.search(p, q) for p in FAMILIES[fam]["keywords"]):
            return fam
    return None


def understand(question: str) -> QuestionUnderstanding:
    fam = classify(question)
    if fam is None:
        return QuestionUnderstanding(
            experiment_family="other", independent_variable="retrieval_k", summary=question.strip()[:200],
            in_scope=False,
            scope_note=("The offline planner only recognises RAG questions about retrieval depth, reranking, "
                        "chunk size/overlap, retriever type, context budget or lost-in-the-middle effects."),
        )
    return QuestionUnderstanding(
        experiment_family=fam, independent_variable=FAMILIES[fam]["iv"], dependent_variable="accuracy",
        summary=f"Test how {FAMILIES[fam]['iv']} affects answer accuracy on rag-eval-v1.",
    )


def hypothesis(family: str) -> Hypothesis:
    f = FAMILIES[family]
    return Hypothesis(
        statement=f["hypothesis"], independent_variable=f["iv"], dependent_variable="accuracy",
        expected_direction=f["direction"], expected_relationship=f["relationship"],
        rationale="Offline template hypothesis (Nemotron not configured).",
    )


def _plan_from_runs(hyp: str, title: str, iv: str, runs: list[RunConfiguration], baseline_id: str) -> ExperimentPlan:
    for r in runs:
        r.is_baseline = r.run_id == baseline_id
    all_keys = set(DEFAULTS)
    varied = {k for k in all_keys if len({repr(r.params.get(k, DEFAULTS[k])) for r in runs}) > 1}
    base_params = next(r.params for r in runs if r.run_id == baseline_id)
    controls = [f"{k}={base_params.get(k, DEFAULTS[k])}" for k in DEFAULTS if k not in varied]
    controls += ["dataset=rag-eval-v1", "reader=extractive (fixed)", "evaluation=exact match", "seed=42"]
    return ExperimentPlan(
        hypothesis=hyp,
        objective=f"Measure the effect of {', '.join(sorted(varied)) or iv} on answer accuracy ({title}).",
        independent_variables=[
            Variable(name=v, description=f"varied: {v}",
                     values=[r.params.get(v, DEFAULTS[v]) for r in runs])
            for v in sorted(varied, key=lambda x: x != iv)
        ] or [Variable(name=iv, values=[])],
        dependent_variables=["accuracy", "retrieval_recall", "context_tokens"],
        control_variables=controls,
        baseline=BaselineSpec(run_id=baseline_id, description=next(r.label for r in runs if r.run_id == baseline_id)),
        configurations=runs,
        metrics=[MetricSpec(name="accuracy", goal="maximize", description="exact-match answer accuracy"),
                 MetricSpec(name="retrieval_recall", goal="maximize", description="answer present in context"),
                 MetricSpec(name="context_tokens", goal="minimize", description="mean context size")],
        primary_metric="accuracy",
        success_criteria=("The hypothesis is supported if accuracy changes in the predicted direction relative to "
                          "the baseline and the paired difference is significant (exact McNemar p < 0.05)."),
        seed=42,
    )


def plan(family: str, hyp: Hypothesis, seed_proposal: NextExperimentProposal | None = None) -> ExperimentPlan:
    if seed_proposal and seed_proposal.configurations:
        runs = [RunConfiguration(**c) for c in seed_proposal.configurations]
        base = next((r.run_id for r in runs if r.is_baseline), runs[0].run_id)
        return _plan_from_runs(hyp.statement, seed_proposal.title, seed_proposal.varied_parameter, runs, base)
    f = FAMILIES[family]
    runs = [RunConfiguration(run_id=rid, label=label, params={**f["base"], **p}) for rid, label, p in f["runs"]]
    return _plan_from_runs(hyp.statement, f["title"], f["iv"], runs, runs[0].run_id)


def analysis(hyp: Hypothesis, stats: StatisticsReport) -> Analysis:
    """Rule-based, fully grounded analysis built only from computed statistics."""
    by_id = {r.run_id: r for r in stats.runs}
    base = by_id[stats.baseline_run_id]
    best = by_id[stats.best_run_id]
    best_cmp = next((c for c in stats.comparisons if c.run_id == best.run_id), None)
    any_sig_up = any(c.significant and c.absolute_diff > 0 for c in stats.comparisons)
    any_sig_down = any(c.significant and c.absolute_diff < 0 for c in stats.comparisons)

    if hyp.expected_direction == "decrease":
        status = "SUPPORTED" if any_sig_down and not any_sig_up else ("REJECTED" if any_sig_up else "INCONCLUSIVE")
    elif hyp.expected_direction == "no_change":
        status = "SUPPORTED" if not (any_sig_up or any_sig_down) else "REJECTED"
    elif hyp.expected_direction == "non_monotonic":
        if not any_sig_up:
            # Shape alone is not evidence: without a significant gain the data cannot support the claim.
            status = "INCONCLUSIVE"
        elif stats.monotonic == "non_monotonic" or stats.diminishing_returns:
            status = "SUPPORTED"
        else:
            status = "PARTIALLY_SUPPORTED"
    else:  # increase
        if any_sig_up and not any_sig_down:
            status = "SUPPORTED"
        elif any_sig_up:
            status = "PARTIALLY_SUPPORTED"
        elif best.run_id != base.run_id and best.accuracy > base.accuracy:
            status = "INCONCLUSIVE"
        else:
            status = "REJECTED"

    findings = [Finding(
        statement=(f"Best configuration {best.run_id} reached {best.accuracy * 100:.1f}% accuracy versus "
                   f"{base.accuracy * 100:.1f}% for the baseline {base.run_id}"
                   + (f" ({best_cmp.absolute_diff_pp:+.1f} pp, McNemar p={best_cmp.mcnemar_p:.3f})." if best_cmp else ".")),
        evidence=[base.run_id, best.run_id] if best.run_id != base.run_id else [base.run_id],
    )]
    if stats.ordered_variable and stats.trend:
        steps = "; ".join(f"{s.from_value}→{s.to_value}: {s.delta_pp:+.1f} pp" for s in stats.trend)
        findings.append(Finding(
            statement=f"Accuracy by {stats.ordered_variable}: {steps}. The pattern is {stats.monotonic.replace('_', '-')}"
                      + (" with diminishing returns." if stats.diminishing_returns else "."),
            evidence=[r.run_id for r in stats.runs],
        ))
    recall_best = max(stats.runs, key=lambda r: r.retrieval_recall)
    if recall_best.run_id != best.run_id and recall_best.retrieval_recall > best.retrieval_recall:
        findings.append(Finding(
            statement=(f"{recall_best.run_id} had the highest retrieval recall ({recall_best.retrieval_recall * 100:.1f}%) "
                       f"but lower accuracy ({recall_best.accuracy * 100:.1f}%) than {best.run_id}: more retrieved "
                       "context did not translate into more correct answers."),
            evidence=[recall_best.run_id, best.run_id],
        ))
    return Analysis(
        summary=(f"{len(stats.runs)} configurations were evaluated on {base.n} questions. "
                 f"{best.run_id} performed best at {best.accuracy * 100:.1f}% accuracy."),
        hypothesis_status=status,
        status_rationale=("Status derived by rule from the direction of the measured differences and their exact "
                          "McNemar significance (offline mode)."),
        key_findings=findings,
        evidence=[r.run_id for r in stats.runs],
        limitations=["Synthetic dataset of 40 questions limits statistical power.",
                     "The reader is a deterministic extractive model, not a generative LLM.",
                     "A single seed and dataset version were used."],
        conclusion=f"Hypothesis {status.replace('_', ' ').lower()} by the measured evidence.",
        source="offline",
    )


def next_experiment(family: str, stats: StatisticsReport) -> NextExperimentProposal:
    nxt = CHAIN.get(family, "retrieval_depth")
    best = next(r for r in stats.runs if r.run_id == stats.best_run_id)
    best_params = {k: v for k, v in best.configuration.items() if k in DEFAULTS and v != DEFAULTS[k]}
    best_params.setdefault("retrieval_k", best.configuration.get("retrieval_k", DEFAULTS["retrieval_k"]))
    f = FAMILIES[nxt]
    if nxt == "reranking":
        base_k = best.configuration.get("retrieval_k", 10)
        configs = [
            {"run_id": "baseline_best", "label": f"best so far (k={base_k}), no reranking",
             "params": {**best_params}, "is_baseline": True},
            {"run_id": "k20_rerank_top5", "label": "k=20 + rerank → top 5",
             "params": {**best_params, "retrieval_k": 20, "reranker": "cross_lite", "rerank_top_n": 5}, "is_baseline": False},
            {"run_id": "k20_rerank_top10", "label": "k=20 + rerank → top 10",
             "params": {**best_params, "retrieval_k": 20, "reranker": "cross_lite", "rerank_top_n": 10}, "is_baseline": False},
        ]
        hyp = (f"Reranking 20 retrieved chunks down to the top 5 will improve accuracy over the best configuration so far "
               f"(retrieval_k={base_k}) by removing look-alike distractors while keeping the relevant evidence.")
        question = "Does reranking a deeper candidate list improve RAG answer accuracy over the best plain top-k setting?"
    else:
        configs = []
        for i, (rid, label, p) in enumerate(f["runs"]):
            params = {**f["base"], **best_params, **p}  # best-so-far config is held fixed
            if params.get("rerank_top_n") and params["rerank_top_n"] > params.get("retrieval_k", 5):
                params["rerank_top_n"] = params.get("retrieval_k", 5)
            configs.append({"run_id": rid, "label": label, "params": params, "is_baseline": i == 0})
        hyp = f["hypothesis"]
        question = f"How does {f['iv']} affect answer accuracy, holding the best configuration so far fixed?"
    return NextExperimentProposal(
        title=f["title"],
        research_question=question,
        hypothesis=hyp,
        rationale=(f"The previous experiment's best configuration was {best.run_id} "
                   f"({best.accuracy * 100:.1f}% accuracy). The next most informative variable is {f['iv']}."),
        varied_parameter=f["iv"],
        baseline={"label": configs[0]["label"], "params": configs[0]["params"]},
        treatment={"label": configs[1]["label"], "params": configs[1]["params"]},
        configurations=configs,
    )
