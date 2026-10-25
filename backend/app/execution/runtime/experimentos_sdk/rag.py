"""A small, dependency-free, fully deterministic RAG pipeline.

Components
----------
* Chunker      — splits each document into word windows (chunk_size / chunk_overlap).
* Retrievers   — ``bm25`` (lexical), ``embedding`` (hashed character-trigram TF-IDF
                 vectors with cosine similarity — a lightweight dense-retrieval proxy)
                 and ``hybrid`` (reciprocal-rank fusion of the two).
* Reranker     — ``cross_lite``: re-scores retrieved chunks with phrase-level features
                 (IDF-weighted overlap, shared bigrams, longest shared token run) and keeps
                 the top ``rerank_top_n``.
* Reader       — an extractive reader that picks the best sentence in the context and
                 extracts a typed answer span. Like real LLM readers it has a positional
                 attention bias (``reader_position_bias``): evidence in the middle of a long
                 context is down-weighted ("lost in the middle"). The reader is held
                 constant across configurations unless an experiment varies it explicitly.

Nothing here is random; identical configurations give identical results.
"""

from __future__ import annotations

import math
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

STOPWORDS = frozenset(
    """a an the of to in on at by for from with and or is are was were be been being it its
    this that these those which who whom what when where why how does do did has have had
    into near than then there their they them as not no our your his her he she we you i
    """.split()
)

RETRIEVERS = ("bm25", "embedding", "hybrid")
RERANKERS = ("none", "cross_lite")

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_SENT_RE = re.compile(r"(?<=[.!?])\s+")


def _stem(tok: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if len(tok) > len(suffix) + 3 and tok.endswith(suffix):
            return tok[: -len(suffix)]
    return tok


def tokenize(text: str) -> list[str]:
    return [_stem(t) for t in _TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]


def approx_tokens(text: str) -> int:
    """Approximate LLM token count (~1.33 tokens per word)."""
    return math.ceil(len(text.split()) * 4 / 3)


@dataclass(frozen=True)
class RAGConfig:
    retrieval_k: int = 5
    chunk_size: int = 128
    chunk_overlap: int = 0
    retriever: str = "bm25"
    reranker: str = "none"
    rerank_top_n: int | None = None
    max_context_tokens: int = 4096
    reader_position_bias: float = 0.30

    def validate(self) -> None:
        if not 1 <= self.retrieval_k <= 50:
            raise ValueError("retrieval_k must be between 1 and 50")
        if not 8 <= self.chunk_size <= 512:
            raise ValueError("chunk_size must be between 8 and 512 words")
        if not 0 <= self.chunk_overlap < self.chunk_size:
            raise ValueError("chunk_overlap must be >= 0 and < chunk_size")
        if self.retriever not in RETRIEVERS:
            raise ValueError(f"retriever must be one of {RETRIEVERS}")
        if self.reranker not in RERANKERS:
            raise ValueError(f"reranker must be one of {RERANKERS}")
        if self.rerank_top_n is not None and not 1 <= self.rerank_top_n <= self.retrieval_k:
            raise ValueError("rerank_top_n must be between 1 and retrieval_k")
        if not 64 <= self.max_context_tokens <= 32768:
            raise ValueError("max_context_tokens must be between 64 and 32768")
        if not 0.0 <= self.reader_position_bias <= 0.9:
            raise ValueError("reader_position_bias must be between 0.0 and 0.9")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Chunk:
    id: str
    doc_id: str
    text: str
    tokens: list[str]
    tf: Counter = field(default_factory=Counter)


class Index:
    """Chunked corpus with BM25 and hashed char-trigram vector indexes."""

    DIM = 4096

    def __init__(self, documents: list[dict], chunk_size: int, chunk_overlap: int):
        self.chunks: list[Chunk] = []
        step = chunk_size - chunk_overlap
        for doc in documents:
            words = doc["text"].split()
            start = 0
            part = 0
            while True:
                window = words[start : start + chunk_size]
                text = " ".join(window)
                toks = tokenize(text)
                self.chunks.append(Chunk(f"{doc['id']}#{part}", doc["id"], text, toks, Counter(toks)))
                part += 1
                if start + chunk_size >= len(words):
                    break
                start += step

        n = len(self.chunks)
        df: Counter = Counter()
        for c in self.chunks:
            df.update(set(c.tokens))
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}
        self.avgdl = sum(len(c.tokens) for c in self.chunks) / max(n, 1)

        # Dense proxy: TF-IDF over hashed character trigrams, L2-normalised.
        tri_df: Counter = Counter()
        tri_tf: list[Counter] = []
        for c in self.chunks:
            grams = Counter(self._trigrams(c.text))
            tri_tf.append(grams)
            tri_df.update(grams.keys())
        self.tri_idf = {g: math.log((1 + n) / (1 + d)) + 1 for g, d in tri_df.items()}
        self.vectors = [self._vectorize(g) for g in tri_tf]

    @staticmethod
    def _trigrams(text: str) -> list[int]:
        s = " " + " ".join(_TOKEN_RE.findall(text.lower())) + " "
        # Deterministic hash (Python's hash() is salted per process).
        return [
            (ord(s[i]) * 961 + ord(s[i + 1]) * 31 + ord(s[i + 2])) % Index.DIM
            for i in range(len(s) - 2)
        ]

    def _vectorize(self, grams: Counter) -> dict[int, float]:
        vec = {g: (1 + math.log(c)) * self.tri_idf.get(g, 1.0) for g, c in grams.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {g: v / norm for g, v in vec.items()}

    def bm25(self, query: str, k: int) -> list[tuple[int, float]]:
        q = tokenize(query)
        k1, b = 1.2, 0.75
        scores = []
        for i, c in enumerate(self.chunks):
            dl = len(c.tokens)
            s = 0.0
            for t in q:
                f = c.tf.get(t, 0)
                if f:
                    s += self.idf[t] * f * (k1 + 1) / (f + k1 * (1 - b + b * dl / self.avgdl))
            scores.append((i, s))
        scores.sort(key=lambda x: (-x[1], x[0]))
        return scores[:k]

    def embedding(self, query: str, k: int) -> list[tuple[int, float]]:
        qv = self._vectorize(Counter(self._trigrams(query)))
        scores = [(i, sum(w * v.get(g, 0.0) for g, w in qv.items())) for i, v in enumerate(self.vectors)]
        scores.sort(key=lambda x: (-x[1], x[0]))
        return scores[:k]

    def hybrid(self, query: str, k: int) -> list[tuple[int, float]]:
        depth = max(k * 3, 30)
        fused: dict[int, float] = {}
        for ranking in (self.bm25(query, depth), self.embedding(query, depth)):
            for rank, (i, _) in enumerate(ranking):
                fused[i] = fused.get(i, 0.0) + 1.0 / (60 + rank + 1)
        out = sorted(fused.items(), key=lambda x: (-x[1], x[0]))
        return out[:k]


def _bigrams(tokens: list[str]) -> set[tuple[str, str]]:
    return set(zip(tokens, tokens[1:]))


def _longest_run(q: list[str], c: list[str]) -> int:
    best = 0
    prev = [0] * (len(c) + 1)
    for i in range(1, len(q) + 1):
        cur = [0] * (len(c) + 1)
        for j in range(1, len(c) + 1):
            if q[i - 1] == c[j - 1]:
                cur[j] = prev[j - 1] + 1
                best = max(best, cur[j])
        prev = cur
    return best


def _entity_tokens(query: str) -> set[str]:
    """Capitalised words after the first word — a cheap proper-noun detector."""
    words = re.findall(r"[A-Za-z0-9]+", query)[1:]
    return {_stem(w.lower()) for w in words if w[0].isupper()} - STOPWORDS


def rerank_cross_lite(index: Index, query: str, hits: list[int]) -> list[int]:
    q = tokenize(query)
    q_set, q_bi = set(q), _bigrams(q)
    entities = _entity_tokens(query)
    scored = []
    for rank, i in enumerate(hits):
        c = index.chunks[i]
        c_set = set(c.tokens)
        overlap = sum(index.idf.get(t, 0.0) for t in q_set & c_set)
        bigram = len(q_bi & _bigrams(c.tokens))
        run = _longest_run(q, c.tokens)
        coverage = len(entities & c_set) / len(entities) if entities else 0.0
        entity = 6.0 * coverage + (4.0 if coverage == 1.0 else 0.0)
        scored.append((overlap + 1.5 * bigram + 1.0 * run + entity, -rank, i))
    scored.sort(reverse=True)
    return [i for _, _, i in scored]


def _attention(pos: int, n: int, bias: float) -> float:
    """U-shaped positional attention: 1.0 at both ends, (1 - bias) in the middle."""
    if n <= 1:
        return 1.0
    return 1.0 - bias * math.sin(math.pi * pos / (n - 1))


def read_answer(
    question: str, chunks: list[str], answer_type: str, vocabulary: dict[str, list[str]], bias: float
) -> tuple[str, int | None]:
    """Return (predicted answer, position of the chunk it came from)."""
    q_set = set(tokenize(question))
    candidates = vocabulary.get(answer_type, [])
    best: tuple[float, int, str] | None = None
    n = len(chunks)
    for pos, text in enumerate(chunks):
        att = _attention(pos, n, bias)
        for sent in _SENT_RE.split(text):
            spans = [(sent.find(v), v) for v in candidates if v in sent]
            if not spans:
                continue
            overlap = len(q_set & set(tokenize(sent)))
            score = overlap * att
            if best is None or score > best[0]:
                best = (score, pos, min(spans)[1])
    if best is None:
        return "", None
    return best[2], best[1]


def _norm(s: str) -> str:
    return " ".join(_TOKEN_RE.findall(s.lower()))


_INDEX_CACHE: dict[tuple[str, int, int], Index] = {}


def get_index(dataset: dict, chunk_size: int, chunk_overlap: int) -> Index:
    key = (dataset.get("version", ""), chunk_size, chunk_overlap)
    if key not in _INDEX_CACHE:
        _INDEX_CACHE[key] = Index(dataset["documents"], chunk_size, chunk_overlap)
    return _INDEX_CACHE[key]


def evaluate_rag(
    dataset: dict,
    config: RAGConfig,
    on_progress: Callable[[int, int], None] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Run the full pipeline over the dataset and return metrics + per-question records."""
    config.validate()
    index = get_index(dataset, config.chunk_size, config.chunk_overlap)
    vocab = dataset["answer_vocabulary"]
    questions = dataset["questions"][: limit or None]
    retrieve = getattr(index, config.retriever)

    records = []
    total_latency = 0.0
    for n_done, q in enumerate(questions, start=1):
        t0 = time.perf_counter()
        hits = [i for i, _ in retrieve(q["question"], config.retrieval_k)]
        if config.reranker == "cross_lite":
            hits = rerank_cross_lite(index, q["question"], hits)
            if config.rerank_top_n:
                hits = hits[: config.rerank_top_n]

        context: list[str] = []
        used = 0
        for i in hits:
            t = approx_tokens(index.chunks[i].text)
            if used + t > config.max_context_tokens:
                break
            context.append(index.chunks[i].text)
            used += t

        predicted, from_pos = read_answer(
            q["question"], context, q["metadata"]["answer_type"], vocab, config.reader_position_bias
        )
        latency = (time.perf_counter() - t0) * 1000
        total_latency += latency

        expected = q["expected_answer"]
        gold_pos = next((p for p, text in enumerate(context) if expected in text), None)
        records.append(
            {
                "question_id": q["id"],
                "question_style": q["metadata"].get("question_style"),
                "expected": expected,
                "predicted": predicted,
                "correct": _norm(predicted) == _norm(expected),
                "answer_in_context": gold_pos is not None,
                "gold_position": gold_pos,
                "answer_position": from_pos,
                "context_chunks": len(context),
                "context_tokens": used,
                "latency_ms": round(latency, 3),
            }
        )
        if on_progress:
            on_progress(n_done, len(questions))

    n = len(records) or 1
    accuracy = sum(r["correct"] for r in records) / n
    recall = sum(r["answer_in_context"] for r in records) / n
    ctx_tokens = sum(r["context_tokens"] for r in records) / n
    # Modelled reader latency: fixed overhead + linear prefill cost per context token.
    est_llm_latency = 180.0 + 0.12 * ctx_tokens
    return {
        "configuration": config.to_dict(),
        "metrics": {
            "accuracy": round(accuracy, 4),
            "retrieval_recall": round(recall, 4),
            "context_tokens": round(ctx_tokens, 1),
            "latency_ms": round(total_latency / n, 3),
            "est_llm_latency_ms": round(est_llm_latency, 1),
            "n_questions": len(records),
            "n_correct": sum(r["correct"] for r in records),
        },
        "per_question": records,
    }
