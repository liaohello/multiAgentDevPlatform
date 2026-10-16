"""Usage ledger and budget gate.

Guarantees implemented here (design: BUDGET_AND_USAGE.md, R12-R15):
- cumulative accounting per goal; usage snapshots are increments, duplicates
  do not double count (dedupe key + monotonic total per thread);
- unresolved reservations are included in admission checks;
- 100% closes the gate for *next* runs; the lock is persisted (restart keeps it);
- resume requires an explicit note and is recorded;
- unknown usage is never treated as zero silently (it is recorded as unknown).
"""
from __future__ import annotations

import json
import threading
from typing import Any

from .db import Database
from .events import EventBus, append_event
from .ids import new_id, now_iso

# Warning thresholds are display levels only (suggested, configurable).
WARN_LEVEL = 0.70
RED_LEVEL = 0.90


class BudgetBlocked(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class Budget:
    def __init__(self, db: Database, bus: EventBus) -> None:
        self.db = db
        self.bus = bus
        self._lock = threading.RLock()
        # Monotonic cumulative totals observed per native thread (for delta calc).
        self._thread_totals: dict[str, int] = {}

    # ---------------------------------------------------------------- ledger
    def record_usage(
        self,
        *,
        goal_id: str | None,
        session_id: str | None,
        run_id: str | None,
        provider: str | None,
        model: str | None,
        breakdown: dict[str, int],
        source: str = "reported",
        exactness: str = "reported",
        dedupe_key: str | None = None,
        workspace_id: str | None = None,
        note: str | None = None,
    ) -> dict | None:
        """Insert a usage event; returns inserted row dict or None if duplicate."""
        row = {
            "id": new_id("usg"),
            "workspace_id": workspace_id,
            "goal_id": goal_id,
            "session_id": session_id,
            "run_id": run_id,
            "provider": provider,
            "model": model,
            "source": source,
            "exactness": exactness,
            "input_tokens": int(breakdown.get("input_tokens", 0) or 0),
            "cached_input_tokens": int(breakdown.get("cached_input_tokens", 0) or 0),
            "output_tokens": int(breakdown.get("output_tokens", 0) or 0),
            "reasoning_output_tokens": int(breakdown.get("reasoning_output_tokens", 0) or 0),
            "total_tokens": int(breakdown.get("total_tokens", 0) or 0),
            "snapshot_json": json.dumps(breakdown.get("snapshot", {}) or {}, ensure_ascii=False),
            "dedupe_key": dedupe_key,
            "ts": now_iso(),
        }
        with self._lock:
            with self.db.write() as conn:
                if dedupe_key:
                    exists = conn.execute(
                        "SELECT id FROM usage_events WHERE dedupe_key = ?", (dedupe_key,)
                    ).fetchone()
                    if exists:
                        return None
                conn.execute(
                    """INSERT INTO usage_events(id, workspace_id, goal_id, session_id, run_id,
                       provider, model, source, exactness, input_tokens, cached_input_tokens,
                       output_tokens, reasoning_output_tokens, total_tokens, snapshot_json,
                       dedupe_key, ts)
                       VALUES (:id,:workspace_id,:goal_id,:session_id,:run_id,:provider,:model,
                       :source,:exactness,:input_tokens,:cached_input_tokens,:output_tokens,
                       :reasoning_output_tokens,:total_tokens,:snapshot_json,:dedupe_key,:ts)""",
                    row,
                )
                append_event(
                    self.db,
                    type_="budget.usage_recorded",
                    payload={
                        "usage_id": row["id"],
                        "tokens": row["total_tokens"],
                        "exactness": exactness,
                        "source": source,
                        "model": model,
                        "note": note,
                    },
                    workspace_id=workspace_id,
                    goal_id=goal_id,
                    session_id=session_id,
                    run_id=run_id,
                    conn=conn,
                )
        self.bus.notify()
        return row

    def thread_snapshot_to_delta(
        self,
        *,
        thread_id: str,
        cumulative_total: int,
        run_id: str | None,
        goal_id: str | None,
        session_id: str | None,
        provider: str | None,
        model: str | None,
        breakdown: dict[str, int] | None = None,
        workspace_id: str | None = None,
    ) -> dict | None:
        """Convert a cumulative thread snapshot into an increment event.

        Duplicate snapshots -> stored once (dedupe key) with 0 increment effect.
        Reset (total lower than previous) -> record observed reset, no deduction,
        exactness='adjusted' (never silently counted as zero).
        """
        with self._lock:
            prev = self._thread_totals.get(thread_id)
            self._thread_totals[thread_id] = cumulative_total
        dedupe = f"thread:{thread_id}:total:{cumulative_total}"
        if prev is None:
            delta = cumulative_total
        elif cumulative_total >= prev:
            delta = cumulative_total - prev
        else:
            # Reset observed: do not deduct; record the observation.
            self.record_usage(
                goal_id=goal_id,
                session_id=session_id,
                run_id=run_id,
                provider=provider,
                model=model,
                breakdown={"total_tokens": 0, "snapshot": {"previous_total": prev, "new_total": cumulative_total}},
                source="snapshot_reset",
                exactness="unknown",
                dedupe_key=dedupe,
                workspace_id=workspace_id,
                note="cumulative usage reset observed; not counted as zero",
            )
            append_event(
                self.db,
                type_="budget.usage_reset_observed",
                payload={"thread_id": thread_id, "previous_total": prev, "new_total": cumulative_total},
                goal_id=goal_id,
                session_id=session_id,
                run_id=run_id,
                workspace_id=workspace_id,
            )
            self.bus.notify()
            return None
        bd = dict(breakdown or {})
        bd["total_tokens"] = delta
        return self.record_usage(
            goal_id=goal_id,
            session_id=session_id,
            run_id=run_id,
            provider=provider,
            model=model,
            breakdown=bd,
            source="thread_snapshot",
            exactness="reported",
            dedupe_key=dedupe,
            workspace_id=workspace_id,
        )

    # ------------------------------------------------------------- aggregates
    def used_tokens(self, goal_id: str) -> int:
        row = self.db.query_one(
            "SELECT COALESCE(SUM(total_tokens),0) AS s FROM usage_events WHERE goal_id = ?",
            (goal_id,),
        )
        return int(row["s"]) if row else 0

    def open_reservations(self, goal_id: str) -> int:
        row = self.db.query_one(
            "SELECT COALESCE(SUM(tokens),0) AS s FROM reservations WHERE goal_id = ? AND status = 'open'",
            (goal_id,),
        )
        return int(row["s"]) if row else 0

    def usage_summary(self, goal_id: str) -> dict:
        goal = self.db.query_one("SELECT budget_tokens, workspace_id FROM goals WHERE id = ?", (goal_id,))
        budget = int(goal["budget_tokens"]) if goal and goal["budget_tokens"] is not None else None
        used = self.used_tokens(goal_id)
        reserved = self.open_reservations(goal_id)
        committed = used + reserved
        ratio = (committed / budget) if budget and budget > 0 else None
        gate_row = self.db.query_one("SELECT * FROM budget_state WHERE goal_id = ?", (goal_id,))
        gate = gate_row["gate"] if gate_row else "OPEN"
        level = "none"
        if ratio is None:
            level = "unconfigured"
        elif ratio >= 1.0:
            level = "blocked"
        elif ratio >= RED_LEVEL:
            level = "red"
        elif ratio >= WARN_LEVEL:
            level = "warn"
        else:
            level = "ok"
        # exactness split
        rows = self.db.query(
            """SELECT exactness, COALESCE(SUM(total_tokens),0) AS s FROM usage_events
               WHERE goal_id = ? GROUP BY exactness""",
            (goal_id,),
        )
        by_exactness = {r["exactness"]: int(r["s"]) for r in rows}
        return {
            "budget_tokens": budget,
            "used_tokens": used,
            "reserved_tokens": reserved,
            "committed_tokens": committed,
            "ratio": ratio,
            "level": level,
            "gate": gate,
            "gate_row": dict(gate_row) if gate_row else None,
            "by_exactness": by_exactness,
        }

    # ------------------------------------------------------------------ gate
    def check_gate_open(self, goal_id: str) -> None:
        """Raise BudgetBlocked if the next execution round is not allowed."""
        summary = self.usage_summary(goal_id)
        if summary["gate"] == "CLOSED":
            raise BudgetBlocked(
                f"budget gate CLOSED: {summary['gate_row']['closed_reason'] if summary['gate_row'] else 'usage reached 100%'}"
            )
        budget = summary["budget_tokens"]
        if budget is None:
            return  # unconfigured budget: no token cap; usage still recorded
        committed = summary["committed_tokens"]
        if budget > 0 and committed * 1.0 / budget >= 1.0:
            # close on the spot (persisted) and refuse
            self.close_gate(
                goal_id,
                reason=f"committed usage {committed} >= budget {budget} (100%)",
                cause="admission",
            )
            raise BudgetBlocked(f"committed usage {committed} >= budget {budget} (100%): next run blocked")
        if budget > 0 and committed * 1.0 / budget >= RED_LEVEL:
            append_event(
                self.db,
                type_="budget.warning",
                payload={"level": "red", "committed": committed, "budget": budget},
                goal_id=goal_id,
            )
        elif budget > 0 and committed * 1.0 / budget >= WARN_LEVEL:
            append_event(
                self.db,
                type_="budget.warning",
                payload={"level": "warn", "committed": committed, "budget": budget},
                goal_id=goal_id,
            )

    def close_gate(self, goal_id: str, *, reason: str, cause: str) -> None:
        with self.db.write() as conn:
            conn.execute(
                """INSERT INTO budget_state(goal_id, gate, closed_at, closed_reason)
                   VALUES (?, 'CLOSED', ?, ?)
                   ON CONFLICT(goal_id) DO UPDATE SET gate='CLOSED',
                     closed_at=excluded.closed_at, closed_reason=excluded.closed_reason""",
                (goal_id, now_iso(), reason),
            )
            append_event(
                self.db,
                type_="budget.closed",
                payload={"reason": reason, "cause": cause},
                goal_id=goal_id,
                conn=conn,
            )
        self.bus.notify()

    def maybe_close_on_threshold(self, goal_id: str) -> None:
        """Called after usage settles; closes the gate when >=100% is reached."""
        summary = self.usage_summary(goal_id)
        budget = summary["budget_tokens"]
        if budget and budget > 0 and summary["committed_tokens"] >= budget:
            if summary["gate"] != "CLOSED":
                self.close_gate(
                    goal_id,
                    reason=f"committed usage {summary['committed_tokens']} >= budget {budget}",
                    cause="usage_settlement",
                )

    def resume_gate(self, goal_id: str, *, note: str, budget_tokens: int | None = None) -> None:
        """Explicit user-approved resume. Optionally adjust the budget."""
        reason_row = self.db.query_one("SELECT * FROM budget_state WHERE goal_id = ?", (goal_id,))
        with self.db.write() as conn:
            if budget_tokens is not None:
                conn.execute("UPDATE goals SET budget_tokens = ? WHERE id = ?", (budget_tokens, goal_id))
            conn.execute(
                """INSERT INTO budget_state(goal_id, gate, resumed_at, resume_note)
                   VALUES (?, 'OPEN', ?, ?)
                   ON CONFLICT(goal_id) DO UPDATE SET gate='OPEN', resumed_at=excluded.resumed_at,
                     resume_note=excluded.resume_note""",
                (goal_id, now_iso(), note),
            )
            append_event(
                self.db,
                type_="budget.resumed",
                payload={
                    "note": note,
                    "previous_closed_reason": reason_row["closed_reason"] if reason_row else None,
                    "budget_tokens": budget_tokens,
                },
                goal_id=goal_id,
                conn=conn,
            )
        self.bus.notify()

    # ---------------------------------------------------------- reservations
    def open_reservation(self, goal_id: str, run_id: str | None, tokens: int, note: str = "") -> str:
        rid = new_id("rsv")
        with self.db.write() as conn:
            conn.execute(
                "INSERT INTO reservations(id, goal_id, run_id, tokens, status, note, created_at)"
                " VALUES (?, ?, ?, ?, 'open', ?, ?)",
                (rid, goal_id, run_id, tokens, note, now_iso()),
            )
            append_event(
                self.db,
                type_="budget.reservation_opened",
                payload={"reservation_id": rid, "tokens": tokens, "note": note},
                goal_id=goal_id,
                run_id=run_id,
                conn=conn,
            )
        self.bus.notify()
        return rid

    def settle_reservation(self, reservation_id: str, note: str = "") -> None:
        with self.db.write() as conn:
            conn.execute(
                "UPDATE reservations SET status='settled', settled_at=? WHERE id=?",
                (now_iso(), reservation_id),
            )
            append_event(
                self.db,
                type_="budget.reservation_settled",
                payload={"reservation_id": reservation_id, "note": note},
                conn=conn,
            )
        self.bus.notify()

    def usage_series(self, goal_id: str) -> list[dict]:
        rows = self.db.query(
            """SELECT ts, total_tokens, run_id, model, exactness,
                      SUM(total_tokens) OVER (ORDER BY ts, id) AS cumulative
               FROM usage_events WHERE goal_id = ? ORDER BY ts, id""",
            (goal_id,),
        )
        return [dict(r) for r in rows]
