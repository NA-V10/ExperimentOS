"""SQLite storage (MVP). A single connection guarded by a lock is plenty for this workload."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    id                    TEXT PRIMARY KEY,
    number                INTEGER NOT NULL UNIQUE,
    title                 TEXT,
    research_question     TEXT NOT NULL,
    hypothesis            TEXT,
    status                TEXT NOT NULL,
    hypothesis_status     TEXT,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    completed_at          TEXT,
    parent_experiment_id  TEXT REFERENCES experiments(id),
    llm_mode              TEXT,
    execution_mode        TEXT,
    featured              INTEGER NOT NULL DEFAULT 0,
    state_json            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_experiments_parent ON experiments(parent_experiment_id);

CREATE TABLE IF NOT EXISTS experiment_runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id  TEXT NOT NULL REFERENCES experiments(id),
    run_id         TEXT NOT NULL,
    label          TEXT,
    configuration  TEXT NOT NULL,
    is_baseline    INTEGER NOT NULL DEFAULT 0,
    status         TEXT NOT NULL DEFAULT 'PENDING',
    started_at     TEXT,
    completed_at   TEXT,
    UNIQUE (experiment_id, run_id)
);

CREATE TABLE IF NOT EXISTS experiment_results (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id  TEXT NOT NULL REFERENCES experiments(id),
    run_id         TEXT NOT NULL,
    configuration  TEXT NOT NULL,
    metrics        TEXT NOT NULL,
    raw_output     TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    UNIQUE (experiment_id, run_id)
);

CREATE TABLE IF NOT EXISTS agent_events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id  TEXT NOT NULL REFERENCES experiments(id),
    event_type     TEXT NOT NULL,
    stage          TEXT,
    tool           TEXT,
    message        TEXT NOT NULL,
    data           TEXT,
    timestamp      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_experiment ON agent_events(experiment_id, id);

CREATE TABLE IF NOT EXISTS datasets (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    version      TEXT NOT NULL,
    path         TEXT NOT NULL,
    n_questions  INTEGER NOT NULL,
    n_documents  INTEGER NOT NULL,
    description  TEXT,
    sha256       TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_sources (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id  TEXT NOT NULL REFERENCES experiments(id),
    title          TEXT NOT NULL,
    url            TEXT NOT NULL,
    snippet        TEXT,
    score          REAL
);
"""


class Database:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            if path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(SCHEMA)

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, params).fetchall())

    def close(self) -> None:
        with self._lock:
            self._conn.close()
