"""Startup integrity check for the bundled evaluation dataset.

If the benchmark is corrupted or hand-edited inconsistently, every measurement
built on it is meaningless — so the app refuses to start instead.
"""

from __future__ import annotations

import json
from pathlib import Path


class DatasetIntegrityError(RuntimeError):
    pass


def check_dataset(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise DatasetIntegrityError(f"cannot read dataset {path}: {e}") from e

    problems: list[str] = []
    for key in ("version", "documents", "questions", "answer_vocabulary"):
        if key not in data:
            problems.append(f"missing top-level key '{key}'")
    if problems:
        raise DatasetIntegrityError(f"{path.name}: " + "; ".join(problems))

    docs = {d["id"]: d["text"] for d in data["documents"]}
    if len(docs) != len(data["documents"]):
        problems.append("duplicate document ids")
    q_ids = [q["id"] for q in data["questions"]]
    if len(q_ids) != len(set(q_ids)):
        problems.append("duplicate question ids")
    vocab = data["answer_vocabulary"]
    for q in data["questions"]:
        meta = q.get("metadata", {})
        gold, answer, atype = meta.get("gold_doc_id"), q.get("expected_answer", ""), meta.get("answer_type")
        if gold not in docs:
            problems.append(f"{q['id']}: gold document {gold!r} does not exist")
        elif answer not in docs[gold]:
            problems.append(f"{q['id']}: expected answer is not in its gold document")
        if atype not in vocab or answer not in vocab.get(atype, []):
            problems.append(f"{q['id']}: answer not in the '{atype}' answer vocabulary")
    if not data["questions"]:
        problems.append("no questions")
    if problems:
        shown = "; ".join(problems[:5]) + (f" (+{len(problems) - 5} more)" if len(problems) > 5 else "")
        raise DatasetIntegrityError(f"{path.name} failed integrity checks: {shown}. "
                                    "Rebuild it with `python scripts/build_dataset.py`.")
    return {"version": data["version"], "questions": len(data["questions"]), "documents": len(docs)}
