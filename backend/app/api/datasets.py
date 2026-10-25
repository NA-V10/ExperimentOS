"""Dataset endpoints (the bundled, versioned DEMO DATASET)."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.get("")
async def list_datasets(request: Request):
    return {"items": request.app.state.repo.list_datasets()}


@router.get("/{dataset_id}")
async def get_dataset(dataset_id: str, request: Request, limit: int = 50):
    rows = [d for d in request.app.state.repo.list_datasets() if d["id"] == dataset_id]
    if not rows:
        raise HTTPException(404, "dataset not found")
    data = json.loads(request.app.state.settings.dataset_path.read_text(encoding="utf-8"))
    questions = [
        {"id": q["id"], "question": q["question"], "expected_answer": q["expected_answer"],
         "answer_type": q["metadata"]["answer_type"], "question_style": q["metadata"]["question_style"],
         "gold_doc_id": q["metadata"]["gold_doc_id"], "n_context": len(q["context"])}
        for q in data["questions"][:limit]
    ]
    docs = {d["id"]: d for d in data["documents"]}
    sample_q = data["questions"][0]
    return {
        **rows[0], "seed": data["seed"], "questions": questions,
        "sample_record": {k: sample_q[k] for k in ("id", "question", "context", "expected_answer", "metadata")},
        "decoy_documents": sum(1 for d in docs.values() if d["metadata"].get("is_decoy")),
    }
