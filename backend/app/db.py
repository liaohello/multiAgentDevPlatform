"""SQLite single-writer persistence. Windows Python owns the only write connection.

State changes and their product events are committed in the same transaction
(see flags in helper methods). Runtime mode (real/simulation) is stored on
sessions/goals/runs and echoed in every event payload by callers.
"""
from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from . import SCHEMA_VERSION

DDL = """
CREATE TABLE IF NOT EXISTS schema_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workspaces (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  windows_path TEXT NOT NULL,
  wsl_path TEXT,
  wsl_distro TEXT,
  fs_side TEXT NOT NULL DEFAULT 'windows',
  authorized_scopes TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  role TEXT NOT NULL,
  name TEXT,
  mode TEXT NOT NULL DEFAULT 'simulation',
  provider TEXT,
  model TEXT,
  reasoning_effort TEXT,
  native_thread_id TEXT,
  state TEXT NOT NULL DEFAULT 'active',
  config_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
);

CREATE TABLE IF NOT EXISTS goals (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  sol_session_id TEXT,
  worker_session_id TEXT,
  title TEXT NOT NULL,
  original_request TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'DRAFT',
  stage TEXT,
  mode TEXT NOT NULL DEFAULT 'simulation',
  budget_tokens INTEGER,
  budget_policy TEXT NOT NULL DEFAULT '{}',
  goal_version INTEGER NOT NULL DEFAULT 1,
  acceptance_version INTEGER NOT NULL DEFAULT 0,
  plan_version INTEGER NOT NULL DEFAULT 0,
  current_plan_id TEXT,
  auto_advance INTEGER NOT NULL DEFAULT 1,
  auto_rounds INTEGER NOT NULL DEFAULT 0,
  completion_note TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
);

CREATE TABLE IF NOT EXISTS criteria (
  id TEXT PRIMARY KEY,
  goal_id TEXT NOT NULL,
  acceptance_version INTEGER NOT NULL,
  criterion_key TEXT NOT NULL,
  text TEXT NOT NULL,
  required INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  FOREIGN KEY (goal_id) REFERENCES goals(id)
);

CREATE TABLE IF NOT EXISTS plan_revisions (
  id TEXT PRIMARY KEY,
  goal_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  content_md TEXT NOT NULL,
  content_json TEXT NOT NULL DEFAULT '{}',
  change_reason TEXT,
  created_by_decision_id TEXT,
  frozen_at TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (goal_id) REFERENCES goals(id)
);

CREATE TABLE IF NOT EXISTS decisions (
  id TEXT PRIMARY KEY,
  goal_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  reason_json TEXT NOT NULL DEFAULT '{}',
  based_on_result_ids TEXT NOT NULL DEFAULT '[]',
  based_on_review_ids TEXT NOT NULL DEFAULT '[]',
  next_action TEXT,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (goal_id) REFERENCES goals(id)
);

CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY,
  goal_id TEXT NOT NULL,
  plan_revision_id TEXT,
  seq INTEGER NOT NULL DEFAULT 1,
  title TEXT NOT NULL DEFAULT '',
  frozen_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  FOREIGN KEY (goal_id) REFERENCES goals(id)
);

CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  goal_id TEXT NOT NULL,
  task_id TEXT,
  decision_id TEXT,
  session_id TEXT,
  mode TEXT NOT NULL DEFAULT 'simulation',
  status TEXT NOT NULL DEFAULT 'QUEUED',
  is_auto INTEGER NOT NULL DEFAULT 0,
  idempotency_key TEXT,
  native_thread_id TEXT,
  native_turn_id TEXT,
  process_ref TEXT,
  error_class TEXT,
  summary_json TEXT NOT NULL DEFAULT '{}',
  started_at TEXT,
  ended_at TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (goal_id) REFERENCES goals(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_idem ON runs(goal_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS results (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  status TEXT NOT NULL,
  summary_json TEXT NOT NULL DEFAULT '{}',
  changes_json TEXT NOT NULL DEFAULT '[]',
  tests_json TEXT NOT NULL DEFAULT '[]',
  evidence_refs TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  FOREIGN KEY (run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS evidence (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  goal_id TEXT,
  run_id TEXT,
  kind TEXT NOT NULL,
  rel_path TEXT NOT NULL,
  sha256 TEXT,
  size INTEGER,
  meta_json TEXT NOT NULL DEFAULT '{}',
  collected_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
  id TEXT PRIMARY KEY,
  goal_id TEXT NOT NULL,
  run_id TEXT,
  result_id TEXT,
  mode TEXT NOT NULL DEFAULT 'simulation',
  plan_version INTEGER,
  acceptance_version INTEGER,
  goal_version INTEGER,
  code_snapshot_ref TEXT,
  verdicts_json TEXT NOT NULL DEFAULT '[]',
  overall TEXT NOT NULL,
  next_action TEXT,
  note TEXT,
  applied INTEGER NOT NULL DEFAULT 0,
  applied_action TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (goal_id) REFERENCES goals(id)
);

CREATE TABLE IF NOT EXISTS usage_events (
  id TEXT PRIMARY KEY,
  workspace_id TEXT,
  goal_id TEXT,
  session_id TEXT,
  run_id TEXT,
  provider TEXT,
  model TEXT,
  source TEXT NOT NULL DEFAULT 'reported',
  exactness TEXT NOT NULL DEFAULT 'reported',
  input_tokens INTEGER NOT NULL DEFAULT 0,
  cached_input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  reasoning_output_tokens INTEGER NOT NULL DEFAULT 0,
  total_tokens INTEGER NOT NULL DEFAULT 0,
  snapshot_json TEXT NOT NULL DEFAULT '{}',
  dedupe_key TEXT,
  ts TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_usage_dedupe ON usage_events(dedupe_key)
  WHERE dedupe_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS reservations (
  id TEXT PRIMARY KEY,
  goal_id TEXT NOT NULL,
  run_id TEXT,
  tokens INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'open',
  note TEXT,
  created_at TEXT NOT NULL,
  settled_at TEXT
);

CREATE TABLE IF NOT EXISTS budget_state (
  goal_id TEXT PRIMARY KEY,
  gate TEXT NOT NULL DEFAULT 'OPEN',
  closed_at TEXT,
  closed_reason TEXT,
  resumed_at TEXT,
  resume_note TEXT,
  FOREIGN KEY (goal_id) REFERENCES goals(id)
);

CREATE TABLE IF NOT EXISTS events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  schema_version TEXT NOT NULL,
  event_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  type TEXT NOT NULL,
  workspace_id TEXT,
  goal_id TEXT,
  session_id TEXT,
  run_id TEXT,
  caused_by TEXT,
  payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_goal ON events(goal_id, seq);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id, seq);

CREATE TABLE IF NOT EXISTS command_receipts (
  key TEXT PRIMARY KEY,
  endpoint TEXT NOT NULL,
  status TEXT NOT NULL,
  response_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS skill_registry (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  version TEXT NOT NULL,
  source TEXT,
  rel_path TEXT,
  content_hash TEXT,
  license TEXT,
  status TEXT NOT NULL DEFAULT 'imported',
  allowed INTEGER NOT NULL DEFAULT 0,
  meta_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_skills (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  skill_id TEXT NOT NULL,
  version TEXT NOT NULL,
  content_hash TEXT,
  frozen_at TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS skill_usage (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  skill_id TEXT NOT NULL,
  state TEXT NOT NULL,
  note TEXT,
  ts TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS wiki_entries (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  rel_path TEXT NOT NULL,
  title TEXT NOT NULL,
  summary TEXT NOT NULL DEFAULT '',
  tags_json TEXT NOT NULL DEFAULT '[]',
  source TEXT,
  content_hash TEXT,
  imported INTEGER NOT NULL DEFAULT 0,
  scope TEXT NOT NULL DEFAULT 'workspace',
  meta_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS imports (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  session_id TEXT,
  goal_id TEXT,
  source_path TEXT NOT NULL,
  stored_rel_path TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  note TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workflow_reports (
  id TEXT PRIMARY KEY,
  goal_id TEXT,
  workspace_id TEXT,
  kind TEXT NOT NULL,
  mode TEXT NOT NULL,
  input_refs TEXT NOT NULL DEFAULT '[]',
  report_json TEXT NOT NULL DEFAULT '{}',
  report_md TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""


class Database:
    """One connection guarded by a lock; all writes serialized in-process."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=10000")
        self.init_schema()

    def init_schema(self) -> None:
        with self.write() as conn:
            conn.executescript(DDL)
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('schema_version', ?)",
                (SCHEMA_VERSION,),
            )

    @contextlib.contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self.conn
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            cur = self.conn.execute(sql, params)
            return cur.fetchall()

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        with self.write() as conn:
            conn.execute(sql, params)


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def parse_json(text: str | None, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default
