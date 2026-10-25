"""Data access for experiments, runs, results, events, datasets and research sources."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..models.agent import AgentEvent, ExperimentState, ResearchSource
from ..models.experiment import ExperimentStatus, RunConfiguration, TERMINAL_STATUSES
from ..models.results import RunResult
from .database import Database


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Repository:
    def __init__(self, db: Database):
        self.db = db

    # --- experiments -------------------------------------------------------------------
    def create_experiment(self, state: ExperimentState, *, parent_id: str | None = None,
                          execution_mode: str = "local", featured: bool = False) -> dict[str, Any]:
        ts = now()
        with self.db.tx() as c:
            number = (c.execute("SELECT COALESCE(MAX(number), 0) + 1 FROM experiments").fetchone()[0])
            exp_id = f"exp_{number:03d}"
            c.execute(
                "INSERT INTO experiments (id, number, title, research_question, status, created_at, updated_at, "
                "parent_experiment_id, llm_mode, execution_mode, featured, state_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (exp_id, number, None, state.research_question, ExperimentStatus.CREATED.value, ts, ts,
                 parent_id, state.llm_mode, execution_mode, int(featured), state.model_dump_json()),
            )
        return self.get_experiment(exp_id)  # type: ignore[return-value]

    def get_experiment(self, exp_id: str) -> dict[str, Any] | None:
        rows = self.db.query("SELECT * FROM experiments WHERE id = ?", (exp_id,))
        return _exp_row(rows[0]) if rows else None

    def get_state(self, exp_id: str) -> ExperimentState:
        rows = self.db.query("SELECT state_json FROM experiments WHERE id = ?", (exp_id,))
        return ExperimentState.model_validate_json(rows[0]["state_json"])

    def list_experiments(self, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM experiments ORDER BY number DESC LIMIT ?", (limit,))
        return [_exp_row(r, with_state=False) for r in rows]

    def children(self, exp_id: str) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM experiments WHERE parent_experiment_id = ? ORDER BY number", (exp_id,))
        return [_exp_row(r, with_state=False) for r in rows]

    def save_state(self, exp_id: str, state: ExperimentState, **cols: Any) -> None:
        cols["state_json"] = state.model_dump_json()
        cols["updated_at"] = now()
        if state.hypothesis:
            cols.setdefault("hypothesis", state.hypothesis.statement)
        if state.analysis:
            cols.setdefault("hypothesis_status", state.analysis.hypothesis_status)
        sets = ", ".join(f"{k} = ?" for k in cols)
        with self.db.tx() as c:
            c.execute(f"UPDATE experiments SET {sets} WHERE id = ?", (*cols.values(), exp_id))

    def set_status(self, exp_id: str, status: ExperimentStatus) -> None:
        cols: dict[str, Any] = {"status": status.value, "updated_at": now()}
        if status in TERMINAL_STATUSES:
            cols["completed_at"] = now()
        sets = ", ".join(f"{k} = ?" for k in cols)
        with self.db.tx() as c:
            c.execute(f"UPDATE experiments SET {sets} WHERE id = ?", (*cols.values(), exp_id))

    def mark_interrupted(self) -> int:
        """On startup, experiments left mid-flight by a previous process can never finish."""
        terminal = tuple(s.value for s in TERMINAL_STATUSES)
        rows = self.db.query(f"SELECT id FROM experiments WHERE status NOT IN ({','.join('?' * len(terminal))})", terminal)
        for r in rows:
            state = self.get_state(r["id"])
            state.error = "Interrupted: the backend restarted while this experiment was in progress."
            self.save_state(r["id"], state)
            self.set_status(r["id"], ExperimentStatus.FAILED)
        return len(rows)

    def dashboard(self) -> dict[str, Any]:
        rows = self.db.query("SELECT status, hypothesis_status FROM experiments")
        out = {"experiments": len(rows), "completed": 0, "running": 0, "failed": 0, "supported": 0,
               "partially_supported": 0, "rejected": 0, "inconclusive": 0}
        for r in rows:
            st = r["status"]
            if st == "COMPLETED":
                out["completed"] += 1
                hs = (r["hypothesis_status"] or "").lower()
                if hs in out:
                    out[hs] += 1
            elif st == "FAILED":
                out["failed"] += 1
            elif st != "CANCELLED":
                out["running"] += 1
        return out

    # --- runs & results ------------------------------------------------------------------
    def replace_runs(self, exp_id: str, configs: list[RunConfiguration]) -> None:
        with self.db.tx() as c:
            c.execute("DELETE FROM experiment_runs WHERE experiment_id = ?", (exp_id,))
            c.executemany(
                "INSERT INTO experiment_runs (experiment_id, run_id, label, configuration, is_baseline, status) "
                "VALUES (?,?,?,?,?, 'PENDING')",
                [(exp_id, cfg.run_id, cfg.label, json.dumps(cfg.params), int(cfg.is_baseline)) for cfg in configs],
            )

    def set_run_status(self, exp_id: str, run_id: str, status: str) -> None:
        col = "started_at" if status == "RUNNING" else "completed_at"
        with self.db.tx() as c:
            c.execute(f"UPDATE experiment_runs SET status = ?, {col} = ? WHERE experiment_id = ? AND run_id = ?",
                      (status, now(), exp_id, run_id))

    def reset_runs(self, exp_id: str) -> None:
        with self.db.tx() as c:
            c.execute("UPDATE experiment_runs SET status='PENDING', started_at=NULL, completed_at=NULL "
                      "WHERE experiment_id = ?", (exp_id,))

    def list_runs(self, exp_id: str) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM experiment_runs WHERE experiment_id = ? ORDER BY id", (exp_id,))
        return [{**dict(r), "configuration": json.loads(r["configuration"]), "is_baseline": bool(r["is_baseline"])}
                for r in rows]

    def save_results(self, exp_id: str, runs: list[RunResult]) -> None:
        ts = now()
        with self.db.tx() as c:
            c.execute("DELETE FROM experiment_results WHERE experiment_id = ?", (exp_id,))
            c.executemany(
                "INSERT INTO experiment_results (experiment_id, run_id, configuration, metrics, raw_output, created_at) "
                "VALUES (?,?,?,?,?,?)",
                [(exp_id, r.run_id, json.dumps(r.configuration), r.metrics.model_dump_json(),
                  json.dumps([q.model_dump() for q in r.per_question]), ts) for r in runs],
            )

    def get_results(self, exp_id: str, include_raw: bool = True) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM experiment_results WHERE experiment_id = ? ORDER BY id", (exp_id,))
        out = []
        for r in rows:
            item = {"run_id": r["run_id"], "configuration": json.loads(r["configuration"]),
                    "metrics": json.loads(r["metrics"]), "created_at": r["created_at"]}
            if include_raw:
                item["per_question"] = json.loads(r["raw_output"])
            out.append(item)
        return out

    # --- events ----------------------------------------------------------------------------
    def add_event(self, ev: AgentEvent) -> AgentEvent:
        with self.db.tx() as c:
            cur = c.execute(
                "INSERT INTO agent_events (experiment_id, event_type, stage, tool, message, data, timestamp) "
                "VALUES (?,?,?,?,?,?,?)",
                (ev.experiment_id, ev.event_type, ev.stage, ev.tool, ev.message, json.dumps(ev.data, default=str),
                 ev.timestamp.isoformat(timespec="milliseconds")),
            )
            ev.id = cur.lastrowid
        return ev

    def list_events(self, exp_id: str, after_id: int = 0) -> list[AgentEvent]:
        rows = self.db.query("SELECT * FROM agent_events WHERE experiment_id = ? AND id > ? ORDER BY id",
                             (exp_id, after_id))
        return [AgentEvent(id=r["id"], experiment_id=r["experiment_id"], event_type=r["event_type"],
                           stage=r["stage"], tool=r["tool"], message=r["message"],
                           data=json.loads(r["data"] or "{}"), timestamp=r["timestamp"]) for r in rows]

    # --- research sources ------------------------------------------------------------------
    def save_sources(self, exp_id: str, sources: list[ResearchSource]) -> None:
        with self.db.tx() as c:
            c.execute("DELETE FROM research_sources WHERE experiment_id = ?", (exp_id,))
            c.executemany("INSERT INTO research_sources (experiment_id, title, url, snippet, score) VALUES (?,?,?,?,?)",
                          [(exp_id, s.title, s.url, s.snippet, s.score) for s in sources])

    def list_sources(self, exp_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.query("SELECT title, url, snippet, score FROM research_sources "
                                               "WHERE experiment_id = ? ORDER BY id", (exp_id,))]

    # --- datasets ---------------------------------------------------------------------------
    def register_dataset(self, path: Path) -> dict[str, Any]:
        raw = path.read_bytes()
        data = json.loads(raw)
        row = (data["version"], data["name"], data["version"], str(path.name), len(data["questions"]),
               len(data["documents"]), data.get("description", ""), hashlib.sha256(raw).hexdigest(), now())
        with self.db.tx() as c:
            c.execute("INSERT OR REPLACE INTO datasets (id, name, version, path, n_questions, n_documents, description, "
                      "sha256, created_at) VALUES (?,?,?,?,?,?,?,?,?)", row)
        return self.list_datasets()[0]

    def list_datasets(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.query("SELECT * FROM datasets ORDER BY id")]


def _exp_row(r, with_state: bool = True) -> dict[str, Any]:
    d = dict(r)
    state = json.loads(d.pop("state_json"))
    d["featured"] = bool(d["featured"])
    analysis = state.get("analysis") or {}
    d["summary"] = analysis.get("summary")
    d["code_source"] = state.get("code_source")
    nxt = state.get("next_experiment")
    d["next_experiment_title"] = nxt.get("title") if nxt else None
    d["error"] = state.get("error")
    if with_state:
        d["state"] = state
    return d
