"""Product event log + SSE fan-out.

Rules enforced here:
- Only allowed fields are persisted; reasoning content and credentials never
  reach this layer (adapters filter before calling).
- State change + event share one transaction at the call site (helpers accept
  an open connection).
- High-frequency text deltas travel on the transient channel (memory only,
  merged for display); the final message is persisted once.
"""
from __future__ import annotations

import json
import threading
from typing import Any, Callable

from . import SCHEMA_VERSION
from .db import Database
from .ids import new_id, now_iso

# Product event types (allowed list). Anything not here is dropped upstream.
ALLOWED_EVENT_TYPES = {
    "workspace.created",
    "workspace.updated",
    "session.created",
    "session.updated",
    "session.resumed",
    "goal.created",
    "goal.planned",
    "goal.plan_revised",
    "goal.activated",
    "goal.paused",
    "goal.resumed",
    "goal.completed",
    "goal.blocked",
    "goal.cancelled",
    "decision.created",
    "run.queued",
    "run.starting",
    "run.started",
    "run.message",
    "run.plan_updated",
    "run.command",
    "run.file_change",
    "run.usage",
    "run.completed",
    "run.failed",
    "run.interrupted",
    "run.status_unknown",
    "run.recovered",
    "evidence.collected",
    "review.created",
    "review.applied",
    "budget.usage_recorded",
    "budget.reservation_opened",
    "budget.reservation_settled",
    "budget.warning",
    "budget.closed",
    "budget.resumed",
    "budget.usage_reset_observed",
    "skill.registry_updated",
    "skill.allowed",
    "skill.session_selected",
    "skill.provided",
    "skill.loaded_observed",
    "wiki.imported",
    "wiki.body_read",
    "wiki.denied",
    "workflow.completed",
    "command.receipt",
    "system.recovered",
    "system.note",
    "error",
}


class EventBus:
    """In-memory fan-out. Persisted events are re-read from the DB by cursor."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._transient: list[dict] = []
        self._tseq = 0

    def notify(self) -> None:
        with self._cond:
            self._cond.notify_all()

    def publish_transient(
        self, *, run_id: str | None, kind: str, text: str, goal_id: str | None = None, role: str | None = None
    ) -> None:
        with self._cond:
            self._tseq += 1
            self._transient.append(
                {
                    "tseq": self._tseq,
                    "run_id": run_id,
                    "goal_id": goal_id,
                    "role": role,
                    "kind": kind,
                    "text": text,
                    "ts": now_iso(),
                }
            )
            if len(self._transient) > 4000:
                self._transient = self._transient[-2000:]
            self._cond.notify_all()

    def read_transient(self, after_tseq: int) -> list[dict]:
        with self._cond:
            return [item for item in self._transient if item["tseq"] > after_tseq]

    def wait(self, timeout: float = 10.0) -> None:
        with self._cond:
            self._cond.wait(timeout=timeout)


def append_event(
    db: Database,
    *,
    type_: str,
    payload: dict | None = None,
    workspace_id: str | None = None,
    goal_id: str | None = None,
    session_id: str | None = None,
    run_id: str | None = None,
    caused_by: str | None = None,
    conn=None,
    bus: EventBus | None = None,
) -> int:
    if type_ not in ALLOWED_EVENT_TYPES:
        raise ValueError(f"event type not allowed: {type_}")
    row = {
        "schema_version": SCHEMA_VERSION,
        "event_id": new_id("evt"),
        "ts": now_iso(),
        "type": type_,
        "workspace_id": workspace_id,
        "goal_id": goal_id,
        "session_id": session_id,
        "run_id": run_id,
        "caused_by": caused_by,
        "payload_json": json.dumps(payload or {}, ensure_ascii=False, default=str),
    }
    sql = (
        "INSERT INTO events(schema_version, event_id, ts, type, workspace_id, goal_id,"
        " session_id, run_id, caused_by, payload_json)"
        " VALUES (:schema_version, :event_id, :ts, :type, :workspace_id, :goal_id,"
        " :session_id, :run_id, :caused_by, :payload_json)"
    )
    if conn is not None:
        cur = conn.execute(sql, row)
        seq = cur.lastrowid
    else:
        with db.write() as c:
            cur = c.execute(sql, row)
            seq = cur.lastrowid
    if bus is not None:
        bus.notify()
    return int(seq)


def list_events(
    db: Database, *, after_seq: int = 0, limit: int = 500, goal_id: str | None = None
) -> list[dict]:
    if goal_id:
        rows = db.query(
            "SELECT * FROM events WHERE seq > ? AND goal_id = ? ORDER BY seq LIMIT ?",
            (after_seq, goal_id, limit),
        )
    else:
        rows = db.query("SELECT * FROM events WHERE seq > ? ORDER BY seq LIMIT ?", (after_seq, limit))
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["payload"] = json.loads(d.pop("payload_json") or "{}")
        except ValueError:
            d["payload"] = {}
        out.append(d)
    return out
