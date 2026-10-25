"""Evidence grounding: every number in an analysis must trace back to a measurement."""

from __future__ import annotations

import re
from typing import Iterable

from ..models.results import Analysis, StatisticsReport
from .statistics import numeric_values

_NUM = re.compile(r"(?<![A-Za-z_])[-+]?\d+(?:\.\d+)?")
# Numbers that are part of identifiers/labels, not claims (e.g. "run_k10", "rag-eval-v1", "95% CI").
_IGNORE = re.compile(r"\b[a-z]+_[a-z0-9_]+\b|rag-eval-v\d+|95%|\bp\s*[<>=]\s*0?\.05\b|\bat 0?\.05\b", re.I)


def analysis_texts(a: Analysis) -> Iterable[str]:
    yield a.summary
    yield a.status_rationale
    yield a.conclusion
    for f in a.key_findings:
        yield f.statement
    yield from a.limitations


def find_ungrounded(texts: Iterable[str], report: StatisticsReport, tolerance: float = 0.06) -> list[str]:
    allowed = numeric_values(report)
    bad: list[str] = []
    for text in texts:
        cleaned = _IGNORE.sub(" ", text or "")
        for m in _NUM.finditer(cleaned):
            token = m.group(0)
            x = abs(float(token))
            # Small integers are ordinal/structural ("two runs", "3 attempts") — allow up to #runs.
            if x.is_integer() and x <= max(len(report.runs), 3):
                continue
            if not any(abs(x - abs(v)) <= tolerance for v in allowed):
                bad.append(token)
    return sorted(set(bad), key=lambda s: float(s))


def unknown_run_ids(a: Analysis, report: StatisticsReport) -> list[str]:
    known = {r.run_id for r in report.runs}
    refs = set(a.evidence) | {e for f in a.key_findings for e in f.evidence}
    return sorted(refs - known)
