"""Question understanding and hypothesis generation with a deterministic quality gate."""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from ..llm.nebius_client import LLMError
from ..models.agent import ResearchContext
from ..models.experiment import PARAMETER_SPACE, Hypothesis, QuestionUnderstanding
from ..models.results import NextExperimentProposal
from . import offline, prompts
from .context import AgentContext

DIRECTION_WORDS = re.compile(
    r"\b(increas\w*|decreas\w*|improv\w*|reduc\w*|rais\w*|lower\w*|higher|more|fewer|less|greater|"
    r"plateau\w*|diminish\w*|declin\w*|outperform\w*|exceed\w*|degrad\w*|saturat\w*|no (significant )?(change|difference)|than)\b",
    re.I,
)
VAGUE = re.compile(r"\b(may or may not|might|could possibly|somehow|in some way|it depends|better overall)\b", re.I)
SPECIFIC = re.compile(r"\d|\b(baseline|none|cross_lite|bm25|embedding|hybrid|rerank\w*)\b", re.I)

_IV_ALIASES = {
    "retrieval_k": ["retrieval_k", "retrieval depth", "retrieved", "top-k", "top k", "k="],
    "chunk_size": ["chunk_size", "chunk size", "chunk"],
    "chunk_overlap": ["chunk_overlap", "overlap"],
    "retriever": ["retriever", "retrieval", "bm25", "embedding", "hybrid"],
    "reranker": ["rerank", "reranker", "reranking"],
    "rerank_top_n": ["rerank", "top_n", "top-n", "top n"],
    "max_context_tokens": ["context", "token"],
    "reader_position_bias": ["position", "bias", "middle"],
}
_DV_ALIASES = {
    "accuracy": ["accuracy", "correct"],
    "retrieval_recall": ["recall"],
    "context_tokens": ["token", "context size"],
    "latency_ms": ["latency"],
    "est_llm_latency_ms": ["latency"],
}


def assess_hypothesis(h: Hypothesis) -> list[str]:
    """Return a list of quality problems (empty = acceptable). Deterministic."""
    problems: list[str] = []
    s = h.statement.lower()
    if len(h.statement.split()) < 10:
        problems.append("statement is too short to be specific (fewer than 10 words)")
    if not any(a in s for a in _IV_ALIASES.get(h.independent_variable, [h.independent_variable])):
        problems.append(f"statement does not mention the independent variable '{h.independent_variable}'")
    if not any(a in s for a in _DV_ALIASES.get(h.dependent_variable, [h.dependent_variable])):
        problems.append(f"statement does not mention the dependent variable '{h.dependent_variable}'")
    if not DIRECTION_WORDS.search(h.statement):
        problems.append("statement does not state an expected direction of change (falsifiability)")
    if VAGUE.search(h.statement):
        problems.append("statement uses hedging language that makes it unfalsifiable")
    if not SPECIFIC.search(h.statement):
        problems.append("statement names no concrete values or conditions (e.g. 'from 3 to 10')")
    return problems


async def understand_question(ctx: AgentContext, question: str) -> QuestionUnderstanding:
    if ctx.offline:
        return offline.understand(question)
    last_err = ""
    for attempt in range(1, ctx.max_attempts + 1):
        try:
            raw = await ctx.llm.complete_json(
                task="understand_question", tier="fast",
                system=prompts.fmt(prompts.UNDERSTAND_SYSTEM),
                user=f"Research question: {question}" + (f"\n\nPrevious output was invalid: {last_err}" if last_err else ""),
                max_tokens=1024,
            )
            u = QuestionUnderstanding.model_validate(raw)
            if u.independent_variable not in PARAMETER_SPACE:
                raise ValueError(f"unknown independent_variable {u.independent_variable!r}")
            return u
        except (ValidationError, ValueError, LLMError) as e:
            last_err = _short(e)
            await ctx.emit("retry", f"Question parsing output invalid (attempt {attempt}/{ctx.max_attempts}): {last_err}",
                           stage="understand")
    # Parsing is a convenience step: fall back to keyword classification rather than failing.
    await ctx.emit("warning", "Falling back to keyword-based question classification.", stage="understand")
    return offline.understand(question)


async def create_hypothesis(
    ctx: AgentContext,
    question: str,
    understanding: QuestionUnderstanding,
    research: ResearchContext | None = None,
    seed_proposal: NextExperimentProposal | None = None,
) -> Hypothesis:
    if ctx.offline:
        if seed_proposal:
            fam = offline.IV_TO_FAMILY.get(seed_proposal.varied_parameter, understanding.experiment_family)
            base = offline.hypothesis(fam if fam in offline.FAMILIES else "retrieval_depth")
            update = {"statement": seed_proposal.hypothesis}
            if seed_proposal.varied_parameter in PARAMETER_SPACE:
                update["independent_variable"] = seed_proposal.varied_parameter
            return base.model_copy(update=update)
        return offline.hypothesis(understanding.experiment_family)

    user = [f"Research question: {question}",
            f"Parsed intent: {understanding.model_dump_json()}"]
    if research and research.searched:
        user.append("Existing evidence (from web search):\n" + json.dumps(
            {"known_findings": research.known_findings, "research_gap": research.research_gap,
             "testable_locally": research.testable_locally}, indent=1))
    if seed_proposal:
        user.append("This experiment follows up a previous one. Proposed hypothesis to refine:\n"
                    + seed_proposal.hypothesis)

    feedback = ""
    for attempt in range(1, ctx.max_attempts + 1):
        try:
            raw = await ctx.llm.complete_json(
                task="create_hypothesis", tier="reasoning",
                system=prompts.fmt(prompts.HYPOTHESIS_SYSTEM),
                user="\n\n".join(user + ([feedback] if feedback else [])),
                max_tokens=2048,
            )
            h = Hypothesis.model_validate(raw)
            problems = assess_hypothesis(h)
            if not problems:
                return h
            feedback = ("Your previous hypothesis was rejected:\n" + h.statement + "\nProblems:\n- "
                        + "\n- ".join(problems) + "\nRevise it.")
            await ctx.emit("retry", f"Hypothesis validation failed (attempt {attempt}/{ctx.max_attempts}). Regenerating...",
                           stage="hypothesis", problems=problems, rejected=h.statement)
        except (ValidationError, LLMError) as e:
            feedback = f"Your previous output was invalid: {_short(e)}. Follow the JSON keys exactly."
            await ctx.emit("retry", f"Hypothesis output invalid (attempt {attempt}/{ctx.max_attempts}): {_short(e)}",
                           stage="hypothesis")
    raise HypothesisError("Nemotron could not produce a valid, falsifiable hypothesis after "
                          f"{ctx.max_attempts} attempts.")


class HypothesisError(Exception):
    pass


def _short(e: Exception) -> str:
    if isinstance(e, ValidationError):
        return "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()[:4])
    return str(e)[:300]
