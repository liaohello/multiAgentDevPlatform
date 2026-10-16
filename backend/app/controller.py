"""Goal controller: the single owner of the planning -> execution -> evidence ->
review -> state-transition loop (R01/R12-R15).

Principles implemented here:
- every model-touching operation passes one admission path (state + permissions
  + budget + single-writer slot + idempotency);
- Review never completes a goal by itself; Python validates versions, evidence
  association and snapshot consistency before applying any transition;
- restart never auto-redispatches tasks and never clears budget locks.
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

from .adapters import TurnCallbacks
from .adapters.codex_appserver import CodexAdapterSession
from .adapters.fake import FakeAdapterSession
from .adapters.wsl import WslCodexAdapterSession, WslTransport
from .budget import Budget, BudgetBlocked
from .config import Settings
from .db import Database, parse_json, row_to_dict
from .events import EventBus, append_event
from .evidence import EvidenceCollector, sha256_file
from .ids import new_id, now_iso
from . import prompts
from .simulation import SimulationDirector, seed_demo_workspace

TERMINAL_GOAL_STATES = {"COMPLETED", "CANCELLED"}


class ConflictError(Exception):
    pass


class Controller:
    def __init__(self, db: Database, bus: EventBus, budget: Budget, evidence: EvidenceCollector, settings: Settings) -> None:
        self.db = db
        self.bus = bus
        self.budget = budget
        self.evidence = evidence
        self.settings = settings
        self.director = SimulationDirector(self)
        self._admit_lock = threading.RLock()
        self._adapters: dict[str, object] = {}
        self._threads: list[threading.Thread] = []
        self.skills = None  # wired by main after construction (SkillManager)
        # Sync mode runs background operations inline; used by deterministic tests.
        import os as _os

        self.sync_mode = _os.environ.get("AGENTPROJ_SYNC_MODE") == "1"

    # =====================================================================
    # accessors used by the simulation director & API
    # =====================================================================
    def get_goal_row(self, goal_id: str):
        return self.db.query_one("SELECT * FROM goals WHERE id = ?", (goal_id,))

    def workspace_path_for_goal(self, goal_id: str) -> str:
        row = self.db.query_one(
            "SELECT w.windows_path FROM goals g JOIN workspaces w ON g.workspace_id = w.id WHERE g.id = ?",
            (goal_id,),
        )
        if not row:
            raise KeyError(f"goal not found: {goal_id}")
        return row["windows_path"]

    def latest_finished_run(self, goal_id: str):
        return self.db.query_one(
            """SELECT * FROM runs WHERE goal_id = ? AND status IN ('SUCCEEDED','FAILED','INTERRUPTED')
               ORDER BY created_at DESC LIMIT 1""",
            (goal_id,),
        )

    def list_run_evidence(self, run_id: str) -> list[dict]:
        rows = self.db.query("SELECT * FROM evidence WHERE run_id = ? ORDER BY collected_at", (run_id,))
        out = []
        for r in rows:
            d = dict(r)
            d["meta"] = parse_json(d.pop("meta_json"), {})
            out.append(d)
        return out

    def get_run_result(self, run_id: str) -> dict | None:
        row = self.db.query_one("SELECT * FROM results WHERE run_id = ? ORDER BY created_at DESC LIMIT 1", (run_id,))
        if not row:
            return None
        d = dict(row)
        d["summary"] = parse_json(d.pop("summary_json"), {})
        d["changes"] = parse_json(d.pop("changes_json"), [])
        d["tests"] = parse_json(d.pop("tests_json"), [])
        d["evidence_refs"] = parse_json(d.pop("evidence_refs"), [])
        return d

    # =====================================================================
    # workspaces & sessions
    # =====================================================================
    def create_workspace(self, name: str, windows_path: str, *, fs_side: str = "windows") -> dict:
        ws_id = new_id("ws")
        wsl_path = self.settings.windows_to_wsl_path(windows_path) if fs_side == "windows" else None
        ts = now_iso()
        with self.db.write() as conn:
            conn.execute(
                """INSERT INTO workspaces(id, name, windows_path, wsl_path, wsl_distro, fs_side,
                   authorized_scopes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (ws_id, name, windows_path, wsl_path, self.settings.wsl_distro, fs_side, "[]", ts, ts),
            )
            append_event(
                self.db,
                type_="workspace.created",
                payload={"name": name, "windows_path": windows_path, "wsl_path": wsl_path},
                workspace_id=ws_id,
                conn=conn,
            )
        self.bus.notify()
        return row_to_dict(self.db.query_one("SELECT * FROM workspaces WHERE id = ?", (ws_id,)))

    def list_workspaces(self) -> list[dict]:
        rows = self.db.query("SELECT * FROM workspaces ORDER BY created_at DESC")
        out = []
        for r in rows:
            d = dict(r)
            d["authorized_scopes"] = parse_json(d["authorized_scopes"], [])
            goal_count = self.db.query_one(
                "SELECT COUNT(*) AS c FROM goals WHERE workspace_id = ?", (r["id"],)
            )
            d["goal_count"] = int(goal_count["c"]) if goal_count else 0
            out.append(d)
        return out

    def create_session(
        self, workspace_id: str, role: str, *, mode: str, model: str | None = None,
        reasoning_effort: str | None = None, provider: str | None = None, name: str | None = None,
    ) -> dict:
        sid = new_id("sess")
        ts = now_iso()
        with self.db.write() as conn:
            conn.execute(
                """INSERT INTO sessions(id, workspace_id, role, name, mode, provider, model,
                   reasoning_effort, native_thread_id, state, config_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 'active', '{}', ?, ?)""",
                (sid, workspace_id, role, name, mode, provider, model, reasoning_effort, ts, ts),
            )
            append_event(
                self.db,
                type_="session.created",
                payload={"role": role, "mode": mode, "model": model, "effort": reasoning_effort},
                workspace_id=workspace_id,
                session_id=sid,
                conn=conn,
            )
        self.bus.notify()
        return row_to_dict(self.db.query_one("SELECT * FROM sessions WHERE id = ?", (sid,)))

    def list_sessions(self, workspace_id: str | None = None) -> list[dict]:
        if workspace_id:
            rows = self.db.query("SELECT * FROM sessions WHERE workspace_id = ? ORDER BY created_at DESC", (workspace_id,))
        else:
            rows = self.db.query("SELECT * FROM sessions ORDER BY created_at DESC")
        return [dict(r) for r in rows]

    def get_session(self, session_id: str) -> dict | None:
        return row_to_dict(self.db.query_one("SELECT * FROM sessions WHERE id = ?", (session_id,)))

    # =====================================================================
    # goals
    # =====================================================================
    def create_goal(
        self,
        *,
        workspace_mode: str = "demo",
        workspace_id: str | None = None,
        title: str,
        request: str,
        mode: str = "simulation",
        budget_tokens: int | None = None,
        scenario: str = "demo",
        auto_advance: bool = True,
        sol_model: str | None = None,
        sol_effort: str | None = None,
        worker_model: str | None = None,
    ) -> dict:
        goal_id = new_id("goal")
        ts = now_iso()

        if workspace_mode == "demo":
            demo_dir = self.settings.demo_workspace / goal_id
            seed_demo_workspace(demo_dir)
            ws = self.create_workspace(f"Demo · {title[:40]}", str(demo_dir))
            workspace_id = ws["id"]

        if not workspace_id:
            raise ConflictError("workspace_id is required for non-demo workspaces")
        workspace = self.db.query_one("SELECT * FROM workspaces WHERE id = ?", (workspace_id,))
        if not workspace:
            raise ConflictError(f"workspace not found: {workspace_id}")

        sol_session = self.create_session(
            workspace_id, "sol", mode=mode, model=sol_model, reasoning_effort=sol_effort,
            provider="openai", name=f"Sol · {title[:24]}",
        )
        worker_session = self.create_session(
            workspace_id, "worker", mode=mode, model=worker_model, reasoning_effort=None,
            provider="deepseek" if mode == "real" else "simulation", name=f"Worker · {title[:24]}",
        )
        with self.db.write() as conn:
            conn.execute(
                """INSERT INTO goals(id, workspace_id, sol_session_id, worker_session_id, title,
                   original_request, status, stage, mode, budget_tokens, budget_policy, goal_version,
                   acceptance_version, plan_version, current_plan_id, auto_advance, auto_rounds,
                   created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'DRAFT', 'draft', ?, ?, ?, 1, 0, 0, NULL, ?, 0, ?, ?)""",
                (
                    goal_id, workspace_id, sol_session["id"], worker_session["id"], title, request,
                    mode, budget_tokens, json.dumps({"scenario": scenario}, ensure_ascii=False),
                    1 if auto_advance else 0, ts, ts,
                ),
            )
            append_event(
                self.db,
                type_="goal.created",
                payload={"title": title, "mode": mode, "budget_tokens": budget_tokens, "scenario": scenario},
                workspace_id=workspace_id,
                goal_id=goal_id,
                session_id=sol_session["id"],
                conn=conn,
            )
        self.bus.notify()
        return self.get_goal_bundle(goal_id)

    def list_goals(self, *, workspace_id: str | None = None) -> list[dict]:
        if workspace_id:
            rows = self.db.query(
                "SELECT * FROM goals WHERE workspace_id = ? ORDER BY created_at DESC", (workspace_id,)
            )
        else:
            rows = self.db.query("SELECT * FROM goals ORDER BY created_at DESC")
        out = []
        for r in rows:
            d = dict(r)
            d["budget"] = self.budget.usage_summary(r["id"])
            out.append(d)
        return out

    def get_goal_bundle(self, goal_id: str) -> dict:
        goal = row_to_dict(self.db.query_one("SELECT * FROM goals WHERE id = ?", (goal_id,)))
        if not goal:
            raise KeyError(goal_id)
        plan = row_to_dict(
            self.db.query_one(
                "SELECT * FROM plan_revisions WHERE goal_id = ? ORDER BY version DESC LIMIT 1", (goal_id,)
            )
        )
        if plan:
            plan["content_json"] = parse_json(plan["content_json"], {})
        plans = [
            row_to_dict(r)
            for r in self.db.query(
                "SELECT id, goal_id, version, change_reason, created_at FROM plan_revisions WHERE goal_id = ? ORDER BY version",
                (goal_id,),
            )
        ]
        criteria = [
            dict(r)
            for r in self.db.query(
                "SELECT * FROM criteria WHERE goal_id = ? ORDER BY criterion_key", (goal_id,)
            )
        ]
        runs = []
        for r in self.db.query(
            "SELECT * FROM runs WHERE goal_id = ? ORDER BY created_at", (goal_id,)
        ):
            d = dict(r)
            d["summary"] = parse_json(d.pop("summary_json"), {})
            d["result"] = self.get_run_result(r["id"])
            d["evidence"] = self.list_run_evidence(r["id"])
            runs.append(d)
        reviews = []
        for r in self.db.query(
            "SELECT * FROM reviews WHERE goal_id = ? ORDER BY created_at", (goal_id,)
        ):
            d = dict(r)
            d["verdicts"] = parse_json(d.pop("verdicts_json"), [])
            reviews.append(d)
        decisions = [
            {**dict(r), "reason": parse_json(r["reason_json"], {})}
            for r in self.db.query("SELECT * FROM decisions WHERE goal_id = ? ORDER BY created_at", (goal_id,))
        ]
        usage = self.budget.usage_summary(goal_id)
        series = self.budget.usage_series(goal_id)
        events = []
        for e in self.db.query(
            "SELECT * FROM events WHERE goal_id = ? ORDER BY seq DESC LIMIT 120", (goal_id,)
        ):
            d = dict(e)
            d["payload"] = parse_json(d.pop("payload_json"), {})
            events.append(d)
        events.reverse()
        workspace = row_to_dict(
            self.db.query_one("SELECT * FROM workspaces WHERE id = ?", (goal["workspace_id"],))
        )
        return {
            "goal": goal,
            "workspace": workspace,
            "plan": plan,
            "plans": plans,
            "criteria": criteria,
            "runs": runs,
            "reviews": reviews,
            "decisions": decisions,
            "usage": usage,
            "usage_series": series,
            "events": events,
        }

    # =====================================================================
    # adapter plumbing
    # =====================================================================
    def _workspace_wsl_path(self, workspace_row) -> str | None:
        wp = workspace_row["wsl_path"]
        return wp

    def _get_adapter(self, goal, session_row):
        key = session_row["id"]
        with self._admit_lock:
            adapter = self._adapters.get(key)
            if adapter is not None:
                return adapter
            workspace = self.db.query_one("SELECT * FROM workspaces WHERE id = ?", (goal["workspace_id"],))
            ws_path = workspace["windows_path"]
            if goal["mode"] == "simulation":
                if session_row["role"] == "sol":
                    handler = self.director.sol_handler(goal["id"])
                else:
                    handler = self.director.worker_handler(goal["id"])
                adapter = FakeAdapterSession(
                    session_id=key, role=session_row["role"], handler=handler, workspace_dir=ws_path
                )
            elif session_row["role"] == "sol":
                adapter = CodexAdapterSession(
                    session_id=key,
                    role="sol",
                    command=[self.settings.codex_bin, "app-server", "--listen", "stdio://"],
                    cwd=ws_path,
                    model=session_row["model"],
                    effort=session_row["reasoning_effort"],
                    native_thread_id=session_row["native_thread_id"],
                    approval_policy="never",
                    sandbox="read-only",
                    label="windows-sol",
                )
            else:
                transport = WslTransport(self.settings.wsl_distro, self.settings.wsl_codex_cmd)
                wsl_cwd = self._workspace_wsl_path(workspace)
                adapter = WslCodexAdapterSession(
                    session_id=key,
                    transport=transport,
                    wsl_cwd=wsl_cwd or "/tmp",
                    model=session_row["model"],
                    effort=session_row["reasoning_effort"],
                    native_thread_id=session_row["native_thread_id"],
                    approval_policy="never",
                    sandbox="workspace-write",
                )
            self._adapters[key] = adapter
            return adapter

    def _persist_session_thread(self, session_id: str, native_thread_id: str) -> None:
        with self.db.write() as conn:
            conn.execute(
                "UPDATE sessions SET native_thread_id = ?, updated_at = ? WHERE id = ?",
                (native_thread_id, now_iso(), session_id),
            )

    def _make_callbacks(self, *, goal, run_row, session_row):
        goal_id = goal["id"]
        run_id = run_row["id"] if run_row else None
        role = session_row["role"]

        def on_delta(kind: str, text: str) -> None:
            self.bus.publish_transient(run_id=run_id, goal_id=goal_id, role=role, kind=kind, text=text)

        def on_product_event(type_: str, payload: dict) -> None:
            try:
                append_event(
                    self.db,
                    type_=type_,
                    payload=payload,
                    workspace_id=goal["workspace_id"],
                    goal_id=goal_id,
                    session_id=session_row["id"],
                    run_id=run_id,
                )
            except ValueError:
                pass  # disallowed type: drop

        def on_usage_total(snapshot: dict) -> None:
            try:
                if goal["mode"] == "simulation" or snapshot.get("incremental"):
                    self.budget.record_usage(
                        goal_id=goal_id,
                        session_id=session_row["id"],
                        run_id=run_id,
                        provider="simulation",
                        model=f"sim-{role}",
                        breakdown=snapshot,
                        source="fake_adapter",
                        exactness="simulated",
                        workspace_id=goal["workspace_id"],
                    )
                else:
                    self.budget.thread_snapshot_to_delta(
                        thread_id=snapshot.get("thread_id") or "",
                        cumulative_total=int(snapshot.get("total_tokens") or 0),
                        run_id=run_id,
                        goal_id=goal_id,
                        session_id=session_row["id"],
                        provider="openai",
                        model=session_row["model"],
                        breakdown={
                            "input_tokens": snapshot.get("input_tokens", 0),
                            "cached_input_tokens": snapshot.get("cached_input_tokens", 0),
                            "output_tokens": snapshot.get("output_tokens", 0),
                            "reasoning_output_tokens": snapshot.get("reasoning_output_tokens", 0),
                            "snapshot": snapshot.get("raw", {}),
                        },
                        workspace_id=goal["workspace_id"],
                    )
            except Exception:
                # usage accounting must never kill a turn
                pass

        return TurnCallbacks(on_delta=on_delta, on_product_event=on_product_event, on_usage_total=on_usage_total)

    def _fail_operation(self, goal_id: str, note: str, stage: str) -> None:
        """Record a planning/review-side failure without touching plan state."""
        goal = self.get_goal_row(goal_id)
        if not goal:
            return
        new_status = goal["status"] if goal["status"] == "DRAFT" else "PAUSED"
        with self.db.write() as conn:
            conn.execute(
                "UPDATE goals SET status=?, stage=?, completion_note=?, updated_at=? WHERE id=?",
                (new_status, stage, note[:500], now_iso(), goal_id),
            )
            append_event(
                self.db, type_="system.note",
                payload={"note": note, "stage": stage},
                workspace_id=goal["workspace_id"], goal_id=goal_id, conn=conn,
            )
        self.bus.notify()

    def _turn_with_schema(self, adapter, prompt: str, schema: dict, cb, *, timeout: float | None = None):
        """One bounded fallback: if the runtime rejects the output schema, retry
        the same prompt without schema (the prompt already requires JSON)."""
        outcome = adapter.start_turn(
            prompt, output_schema=schema, callbacks=cb, timeout=timeout or self.settings.turn_timeout_sec
        )
        if outcome.status == "failed" and outcome.error and "Invalid schema" in outcome.error:
            append_event(
                self.db, type_="system.note",
                payload={"note": "runtime rejected outputSchema; retried once without schema constraint"},
            )
            outcome = adapter.start_turn(prompt, callbacks=cb, timeout=timeout or self.settings.turn_timeout_sec)
        return outcome

    # =====================================================================
    # operations: plan / run / review
    # =====================================================================
    def plan_goal_async(self, goal_id: str, note: str | None = None) -> dict:
        goal = self.get_goal_row(goal_id)
        if not goal:
            raise KeyError(goal_id)
        if goal["status"] not in ("DRAFT", "READY", "PAUSED"):
            raise ConflictError(f"goal status {goal['status']} does not allow planning")
        if self.sync_mode:
            self._plan_goal(goal_id, note)
        else:
            t = threading.Thread(target=self._plan_goal, args=(goal_id, note), name=f"plan-{goal_id}", daemon=True)
            t.start()
            self._threads.append(t)
        return {"accepted": True, "operation": "plan", "goal_id": goal_id}

    def _plan_goal(self, goal_id: str, note: str | None) -> None:
        goal = self.get_goal_row(goal_id)
        session_row = self.get_session(goal["sol_session_id"])
        workspace = row_to_dict(self.db.query_one("SELECT * FROM workspaces WHERE id = ?", (goal["workspace_id"],)))
        try:
            self.budget.check_gate_open(goal_id)
            adapter = self._get_adapter(goal, session_row)
            avail = adapter.availability()
            if avail["status"] != "PASS":
                self._fail_operation(goal_id, f"sol adapter unavailable: {avail['detail']}", stage="plan_blocked")
                return
            native_tid = adapter.ensure_thread(
                model=session_row["model"], effort=session_row["reasoning_effort"], cwd=workspace["windows_path"]
            )
            self._persist_session_thread(session_row["id"], native_tid)
            append_event(
                self.db,
                type_="session.resumed",
                payload={"role": "sol", "thread_id": native_tid, "action": "plan"},
                workspace_id=goal["workspace_id"], goal_id=goal_id, session_id=session_row["id"],
            )
            prior = self.db.query_one(
                "SELECT content_md FROM plan_revisions WHERE goal_id = ? ORDER BY version DESC LIMIT 1", (goal_id,)
            )
            prompt = prompts.build_plan_prompt(
                dict(goal), workspace, prior_plan_md=prior["content_md"] if prior else None, failure_note=note
            )
            cb = self._make_callbacks(goal=goal, run_row=None, session_row=session_row)
            outcome = self._turn_with_schema(adapter, prompt, prompts.PLAN_OUTPUT_SCHEMA, cb)
            if outcome.status != "completed":
                self._fail_operation(goal_id, f"planning turn {outcome.status}: {outcome.error or ''}", stage="plan_failed")
                return
            try:
                plan_json = _extract_json(outcome.final_message)
            except ValueError as exc:
                self._fail_operation(goal_id, f"plan output was not valid JSON: {exc}", stage="plan_failed")
                return
            self._apply_plan(goal_id, plan_json, reason=note or "initial plan", created_by="sol")
        except BudgetBlocked as exc:
            self._fail_operation(goal_id, f"budget blocked planning: {exc.reason}", stage="budget_blocked")
        except Exception as exc:  # noqa: BLE001 - record and surface
            self._fail_operation(goal_id, f"planning error: {exc}", stage="plan_failed")

    def _apply_plan(self, goal_id: str, plan_json: dict, *, reason: str, created_by: str) -> None:
        goal = self.get_goal_row(goal_id)
        next_version = int(goal["plan_version"] or 0) + 1
        plan_id = new_id("plan")
        content_md = _plan_to_markdown(plan_json)
        acceptance = plan_json.get("acceptance") or []
        if not acceptance:
            acceptance = [{"key": "C1", "text": "完成用户原始需求", "required": True}]
        with self.db.write() as conn:
            conn.execute(
                """INSERT INTO plan_revisions(id, goal_id, version, content_md, content_json,
                   change_reason, created_by_decision_id, frozen_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)""",
                (plan_id, goal_id, next_version, content_md,
                 json.dumps(plan_json, ensure_ascii=False), reason, now_iso(), now_iso()),
            )
            if next_version == 1:
                # acceptance criteria frozen with plan v1; acceptance_version = 1
                for item in acceptance:
                    conn.execute(
                        """INSERT INTO criteria(id, goal_id, acceptance_version, criterion_key, text, required, created_at)
                           VALUES (?, ?, 1, ?, ?, ?, ?)""",
                        (
                            new_id("crit"), goal_id, str(item.get("key") or "C?"), str(item.get("text") or ""),
                            1 if item.get("required", True) else 0, now_iso(),
                        ),
                    )
            dec_id = new_id("dec")
            conn.execute(
                """INSERT INTO decisions(id, goal_id, kind, reason_json, based_on_result_ids,
                   based_on_review_ids, next_action, created_by, created_at)
                   VALUES (?, ?, 'plan', ?, '[]', '[]', 'execute', ?, ?)""",
                (dec_id, goal_id, json.dumps({"reason": reason}, ensure_ascii=False), created_by, now_iso()),
            )
            conn.execute(
                """UPDATE plan_revisions SET created_by_decision_id = ? WHERE id = ?""", (dec_id, plan_id)
            )
            first_version = next_version == 1
            if first_version:
                conn.execute(
                    """UPDATE goals SET plan_version = ?, current_plan_id = ?, status = 'READY',
                       stage = 'planned', acceptance_version = 1, updated_at = ? WHERE id = ?""",
                    (next_version, plan_id, now_iso(), goal_id),
                )
            else:
                conn.execute(
                    """UPDATE goals SET plan_version = ?, current_plan_id = ?, status = 'READY',
                       stage = 'planned', updated_at = ? WHERE id = ?""",
                    (next_version, plan_id, now_iso(), goal_id),
                )
            append_event(
                self.db,
                type_="goal.planned" if first_version else "goal.plan_revised",
                payload={"plan_id": plan_id, "version": next_version, "reason": reason},
                workspace_id=goal["workspace_id"], goal_id=goal_id, conn=conn,
            )
            append_event(
                self.db,
                type_="decision.created",
                payload={"decision_id": dec_id, "kind": "plan", "next_action": "execute", "reason": reason},
                workspace_id=goal["workspace_id"], goal_id=goal_id, conn=conn,
            )
        self.bus.notify()

    # ------------------------------------------------------------------ runs
    def start_run_async(self, goal_id: str, *, idempotency_key: str | None = None, is_auto: bool = False) -> dict:
        run, duplicate = self._admit_run(goal_id, idempotency_key=idempotency_key, is_auto=is_auto)
        if duplicate:
            return {"accepted": True, "duplicate": True, "run_id": run["id"], "status": run["status"]}
        if self.sync_mode:
            self._execute_run(run["id"])
        else:
            t = threading.Thread(target=self._execute_run, args=(run["id"],), name=f"run-{run['id']}", daemon=True)
            t.start()
            self._threads.append(t)
        return {"accepted": True, "duplicate": False, "run_id": run["id"], "status": run["status"]}

    def _admit_run(self, goal_id: str, *, idempotency_key: str | None, is_auto: bool) -> tuple[dict, bool]:
        with self._admit_lock:
            if idempotency_key:
                existing = self.db.query_one(
                    "SELECT * FROM runs WHERE goal_id = ? AND idempotency_key = ?", (goal_id, idempotency_key)
                )
                if existing:
                    return dict(existing), True
            goal = self.get_goal_row(goal_id)
            if not goal:
                raise KeyError(goal_id)
            if goal["status"] in TERMINAL_GOAL_STATES:
                raise ConflictError(f"goal is {goal['status']}; cannot start a new run")
            if goal["status"] == "PAUSED":
                raise ConflictError("goal is PAUSED; resume it before starting a run")
            if goal["status"] == "DRAFT":
                raise ConflictError("goal has no frozen plan yet; run planning first")
            active = self.db.query_one(
                """SELECT r.id, r.status FROM runs r JOIN goals g ON r.goal_id = g.id
                   WHERE g.workspace_id = ? AND r.status IN ('QUEUED','STARTING','RUNNING','STOP_REQUESTED')
                   LIMIT 1""",
                (goal["workspace_id"],),
            )
            if active:
                raise ConflictError(
                    f"workspace already has an active run {active['id']} ({active['status']}); one writer per directory"
                )
            if is_auto:
                if not goal["auto_advance"]:
                    raise ConflictError("auto advance disabled for this goal")
                if int(goal["auto_rounds"] or 0) >= self.settings.max_auto_rounds:
                    raise ConflictError(f"max auto rounds reached ({self.settings.max_auto_rounds})")
            self.budget.check_gate_open(goal_id)

            plan = row_to_dict(
                self.db.query_one("SELECT * FROM plan_revisions WHERE id = ?", (goal["current_plan_id"],))
            )
            plan_json = parse_json(plan["content_json"], {}) if plan else {}
            tasks = plan_json.get("tasks") or [
                {"title": "执行计划", "instructions": "按计划完成实现与测试。", "verify_commands": [["{python}", "-m", "pytest", "-q"]]}
            ]
            # pick task by run count (v1 -> task 0; after fix plan -> its first task)
            task_row = tasks[0]
            task_id = new_id("task")
            run_id = new_id("run")
            ts = now_iso()
            frozen = {
                "task_id": task_id,
                "title": task_row.get("title") or "任务",
                "instructions": task_row.get("instructions") or "",
                "deliverable": task_row.get("deliverable"),
                "verify_commands": task_row.get("verify_commands") or [["{python}", "-m", "pytest", "-q"]],
                "goal_version": int(goal["goal_version"]),
                "plan_version": int(goal["plan_version"]),
                "acceptance_version": int(goal["acceptance_version"]),
                "plan_id": goal["current_plan_id"],
                "workspace_id": goal["workspace_id"],
                "frozen_at": ts,
            }
            with self.db.write() as conn:
                conn.execute(
                    """INSERT INTO tasks(id, goal_id, plan_revision_id, seq, title, frozen_json, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (task_id, goal_id, goal["current_plan_id"], int(goal["plan_version"]), task_row.get("title") or "任务",
                     json.dumps(frozen, ensure_ascii=False), ts),
                )
                decision_id = new_id("dec")
                conn.execute(
                    """INSERT INTO decisions(id, goal_id, kind, reason_json, based_on_result_ids,
                       based_on_review_ids, next_action, created_by, created_at)
                       VALUES (?, ?, 'execute', ?, '[]', '[]', 'run', ?, ?)""",
                    (decision_id, goal_id, json.dumps({"is_auto": is_auto}, ensure_ascii=False), "controller", ts),
                )
                conn.execute(
                    """INSERT INTO runs(id, goal_id, task_id, decision_id, session_id, mode, status,
                       is_auto, idempotency_key, created_at) VALUES (?, ?, ?, ?, ?, ?, 'QUEUED', ?, ?, ?)""",
                    (run_id, goal_id, task_id, decision_id, goal["worker_session_id"], goal["mode"],
                     1 if is_auto else 0, idempotency_key, ts),
                )
                if is_auto:
                    conn.execute(
                        "UPDATE goals SET auto_rounds = auto_rounds + 1, status = 'ACTIVE', stage = 'executing', updated_at = ? WHERE id = ?",
                        (ts, goal_id),
                    )
                else:
                    conn.execute(
                        "UPDATE goals SET status = 'ACTIVE', stage = 'executing', updated_at = ? WHERE id = ?",
                        (ts, goal_id),
                    )
                append_event(
                    self.db,
                    type_="run.queued",
                    payload={"task_id": task_id, "is_auto": is_auto, "plan_version": frozen["plan_version"]},
                    workspace_id=goal["workspace_id"], goal_id=goal_id, run_id=run_id, conn=conn,
                )
                append_event(
                    self.db,
                    type_="decision.created",
                    payload={"decision_id": decision_id, "kind": "execute", "next_action": "run"},
                    workspace_id=goal["workspace_id"], goal_id=goal_id, run_id=run_id, conn=conn,
                )
            self.bus.notify()
            if self.skills is not None:
                try:
                    self.skills.freeze_for_run(run_id, goal["worker_session_id"])
                except Exception:
                    pass  # skill freezing must never break admission
            return dict(self.db.query_one("SELECT * FROM runs WHERE id = ?", (run_id,))), False

    def _execute_run(self, run_id: str) -> None:
        run = row_to_dict(self.db.query_one("SELECT * FROM runs WHERE id = ?", (run_id,)))
        goal = self.get_goal_row(run["goal_id"])
        session_row = self.get_session(run["session_id"])
        task_row = row_to_dict(self.db.query_one("SELECT * FROM tasks WHERE id = ?", (run["task_id"],)))
        frozen = parse_json(task_row["frozen_json"], {}) if task_row else {}
        workspace = row_to_dict(self.db.query_one("SELECT * FROM workspaces WHERE id = ?", (goal["workspace_id"],)))
        ws_path = workspace["windows_path"]
        criteria = [
            {**dict(r)} for r in self.db.query("SELECT * FROM criteria WHERE goal_id = ? ORDER BY criterion_key", (goal["id"],))
        ]
        before_snapshot = self.evidence.snapshot_workspace(ws_path)
        reservation_id: str | None = None
        try:
            with self.db.write() as conn:
                conn.execute("UPDATE runs SET status='STARTING', started_at=? WHERE id=?", (now_iso(), run_id))
                append_event(
                    self.db, type_="run.starting", payload={"run_id": run_id},
                    workspace_id=goal["workspace_id"], goal_id=goal["id"], run_id=run_id, conn=conn,
                )
            self.bus.notify()

            adapter = self._get_adapter(goal, session_row)
            avail = adapter.availability()
            if avail["status"] != "PASS":
                self._finish_run_with_failure(
                    run_id, goal, class_="ADAPTER_BLOCKED",
                    note=f"worker adapter unavailable: {avail['detail']}",
                )
                return

            wsl_cwd = None
            if goal["mode"] == "real" and session_row["role"] == "worker":
                wsl_cwd = workspace["wsl_path"]
            native_tid = adapter.ensure_thread(
                model=session_row["model"], effort=session_row["reasoning_effort"],
                cwd=ws_path if goal["mode"] == "simulation" or session_row["role"] == "sol" else None,
            )
            self._persist_session_thread(session_row["id"], native_tid)
            with self.db.write() as conn:
                conn.execute(
                    "UPDATE runs SET status='RUNNING', native_thread_id=? WHERE id=?", (native_tid, run_id)
                )
                append_event(
                    self.db,
                    type_="run.started",
                    payload={"run_id": run_id, "role": session_row["role"], "thread_id": native_tid,
                             "model": session_row["model"], "mode": goal["mode"]},
                    workspace_id=goal["workspace_id"], goal_id=goal["id"], session_id=session_row["id"],
                    run_id=run_id, conn=conn,
                )
            self.bus.notify()

            round_note = self._last_review_note(goal["id"])
            prompt = prompts.build_worker_prompt(
                dict(goal), frozen, criteria, workspace, round_note=round_note
            )
            cb = self._make_callbacks(goal=goal, run_row=run, session_row=session_row)
            outcome = adapter.start_turn(prompt, callbacks=cb, timeout=self.settings.turn_timeout_sec)

            worker_report: dict | None = None
            if outcome.status == "completed":
                try:
                    worker_report = _extract_json(outcome.final_message)
                except ValueError:
                    # bounded format repair: exactly one follow-up turn
                    repair_prompt = (
                        "你的上一条回复不是有效的 JSON。请严格按以下格式只输出一个 JSON 对象：\n"
                        + prompts.WORKER_RESULT_FORMAT
                    )
                    outcome2 = adapter.start_turn(repair_prompt, callbacks=cb, timeout=self.settings.turn_timeout_sec)
                    if outcome2.status == "completed":
                        outcome = outcome2
                        try:
                            worker_report = _extract_json(outcome.final_message)
                        except ValueError:
                            worker_report = None

            with self.db.write() as conn:
                conn.execute(
                    "UPDATE runs SET native_turn_id=?, ended_at=?, summary_json=? WHERE id=?",
                    (outcome.turn_id, now_iso(), json.dumps({"report": worker_report}, ensure_ascii=False), run_id),
                )

            if outcome.status == "interrupted":
                self._finish_run_interrupted(run_id, goal)
                return
            if outcome.status != "completed":
                self._finish_run_with_failure(
                    run_id, goal, class_=outcome.status.upper(),
                    note=outcome.error or f"turn ended with status {outcome.status}",
                )
                return

            # evidence collection (verifications run by the program, not the worker)
            verify_commands = frozen.get("verify_commands") or [["{python}", "-m", "pytest", "-q"]]
            collected = self.evidence.collect_for_run(
                goal=dict(goal), run_id=run_id, workspace_id=goal["workspace_id"],
                workspace_path=ws_path, before_snapshot=before_snapshot,
                verify_commands=verify_commands,
            )
            tests = collected["tests"]
            report_status = (worker_report or {}).get("status")
            verify_codes = [t.get("exit_code") for t in tests if t.get("exit_code") is not None]
            evidence_ok = bool(verify_codes) and all(c == 0 for c in verify_codes)
            if report_status == "failed" or not evidence_ok:
                result_status = "failed"
            else:
                result_status = "completed"
            contradiction = report_status == "completed" and not evidence_ok
            if not worker_report:
                note = "worker final message was not valid JSON; result recorded without parsed report"
            elif contradiction:
                note = "worker reported success but program-collected evidence shows failing verifications"
            else:
                note = ""
            result_id = new_id("res")
            with self.db.write() as conn:
                conn.execute(
                    """INSERT INTO results(id, run_id, status, summary_json, changes_json, tests_json,
                       evidence_refs, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        result_id, run_id, result_status,
                        json.dumps({"report": worker_report, "note": note}, ensure_ascii=False),
                        json.dumps(collected["changed_files"], ensure_ascii=False),
                        json.dumps(tests, ensure_ascii=False),
                        json.dumps(collected["evidence_ids"], ensure_ascii=False),
                        now_iso(),
                    ),
                )
                conn.execute("UPDATE runs SET status='SUCCEEDED', ended_at=? WHERE id=?", (now_iso(), run_id))
                append_event(
                    self.db,
                    type_="run.completed",
                    payload={"result_id": result_id, "result_status": result_status,
                             "tests": [{"exit_code": t.get("exit_code")} for t in tests],
                             "changed_files": [c["path"] for c in collected["changed_files"]]},
                    workspace_id=goal["workspace_id"], goal_id=goal["id"],
                    session_id=session_row["id"], run_id=run_id, conn=conn,
                )
                conn.execute(
                    """INSERT INTO command_receipts(key, endpoint, status, response_json, created_at)
                       VALUES (?, ?, ?, ?, ?) ON CONFLICT(key) DO NOTHING""",
                    (f"run:{run_id}", "/api/goals/run", "completed",
                     json.dumps({"run_id": run_id, "result_status": result_status}, ensure_ascii=False), now_iso()),
                )
            self.bus.notify()
            self.budget.maybe_close_on_threshold(goal["id"])
        except BudgetBlocked as exc:
            self._finish_run_with_failure(run_id, goal, class_="BUDGET_BLOCKED", note=exc.reason)
        except Exception as exc:  # noqa: BLE001
            self._finish_run_with_failure(run_id, goal, class_="EXECUTION_ERROR", note=str(exc))
        finally:
            if reservation_id:
                self.budget.settle_reservation(reservation_id)
            self._maybe_auto_review(run_id)

    def _last_review_note(self, goal_id: str) -> str | None:
        row = self.db.query_one(
            "SELECT note FROM reviews WHERE goal_id = ? ORDER BY created_at DESC LIMIT 1", (goal_id,)
        )
        return row["note"] if row and row["note"] else None

    def _finish_run_with_failure(self, run_id: str, goal, *, class_: str, note: str) -> None:
        with self.db.write() as conn:
            conn.execute(
                "UPDATE runs SET status='FAILED', error_class=?, ended_at=?, summary_json=? WHERE id=?",
                (class_, now_iso(), json.dumps({"note": note}, ensure_ascii=False), run_id),
            )
            conn.execute(
                """INSERT INTO results(id, run_id, status, summary_json, created_at)
                   VALUES (?, ?, 'failed', ?, ?)""",
                (new_id("res"), run_id, json.dumps({"note": note, "error_class": class_}, ensure_ascii=False), now_iso()),
            )
            append_event(
                self.db, type_="run.failed",
                payload={"error_class": class_, "note": note[:2000]},
                workspace_id=goal["workspace_id"], goal_id=goal["id"], run_id=run_id, conn=conn,
            )
            # transport-level failure pauses the goal; no automatic retry (design §21)
            conn.execute(
                "UPDATE goals SET status='PAUSED', stage='run_failed', completion_note=?, updated_at=? WHERE id=?",
                (note[:500], now_iso(), goal["id"]),
            )
        self.bus.notify()

    def _finish_run_interrupted(self, run_id: str, goal) -> None:
        with self.db.write() as conn:
            conn.execute(
                "UPDATE runs SET status='INTERRUPTED', ended_at=? WHERE id=?", (now_iso(), run_id)
            )
            conn.execute(
                """INSERT INTO results(id, run_id, status, summary_json, created_at)
                   VALUES (?, ?, 'interrupted', '{}', ?)""",
                (new_id("res"), run_id, now_iso()),
            )
            append_event(
                self.db, type_="run.interrupted", payload={"run_id": run_id},
                workspace_id=goal["workspace_id"], goal_id=goal["id"], run_id=run_id, conn=conn,
            )
            conn.execute(
                "UPDATE goals SET stage='run_interrupted', updated_at=? WHERE id=?", (now_iso(), goal["id"])
            )
        self.bus.notify()

    def _maybe_auto_review(self, run_id: str) -> None:
        run = row_to_dict(self.db.query_one("SELECT * FROM runs WHERE id = ?", (run_id,)))
        if not run:
            return
        goal = self.get_goal_row(run["goal_id"])
        if not goal or goal["status"] != "ACTIVE":
            return
        if run["status"] not in ("SUCCEEDED",):
            return
        if not goal["auto_advance"]:
            return
        self._spawn_review(goal["id"], run_id, is_auto=True)

    def review_goal_async(self, goal_id: str, *, idempotency_key: str | None = None) -> dict:
        run = self.latest_finished_run(goal_id)
        if not run or run["status"] != "SUCCEEDED":
            raise ConflictError("no finished run available for review")
        if idempotency_key:
            existing = self.db.query_one(
                "SELECT * FROM reviews WHERE goal_id = ? AND run_id = ? ORDER BY created_at DESC LIMIT 1",
                (goal_id, run["id"]),
            )
            if existing:
                return {"accepted": True, "duplicate": True, "review_id": existing["id"]}
        self._spawn_review(goal_id, run["id"], is_auto=False)
        return {"accepted": True, "duplicate": False, "run_id": run["id"]}

    def _spawn_review(self, goal_id: str, run_id: str, *, is_auto: bool) -> None:
        goal = self.get_goal_row(goal_id)
        if goal["status"] == "PAUSED":
            append_event(
                self.db, type_="system.note",
                payload={"note": "review skipped: goal paused"}, goal_id=goal_id, run_id=run_id,
            )
            return
        try:
            self.budget.check_gate_open(goal_id)
        except BudgetBlocked as exc:
            append_event(
                self.db, type_="budget.closed",
                payload={"reason": exc.reason, "cause": "review_admission"},
                workspace_id=goal["workspace_id"], goal_id=goal_id, run_id=run_id,
            )
            with self.db.write() as conn:
                conn.execute(
                    "UPDATE goals SET status='PAUSED', stage='budget_blocked', completion_note=?, updated_at=? WHERE id=?",
                    (f"预算门禁关闭：{exc.reason}", now_iso(), goal_id),
                )
            self.bus.notify()
            return
        t = threading.Thread(
            target=self._run_review, args=(goal_id, run_id, is_auto), name=f"review-{goal_id}", daemon=True
        )
        if self.sync_mode:
            t.run()
        else:
            t.start()
            self._threads.append(t)

    def _run_review(self, goal_id: str, run_id: str, is_auto: bool) -> None:
        goal = self.get_goal_row(goal_id)
        run = row_to_dict(self.db.query_one("SELECT * FROM runs WHERE id = ?", (run_id,)))
        session_row = self.get_session(goal["sol_session_id"])
        result = self.get_run_result(run_id) or {}
        evidence = self.list_run_evidence(run_id)
        criteria = [
            dict(r) for r in self.db.query("SELECT * FROM criteria WHERE goal_id = ? ORDER BY criterion_key", (goal_id,))
        ]
        plan = row_to_dict(self.db.query_one("SELECT * FROM plan_revisions WHERE id = ?", (goal["current_plan_id"],)))
        workspace = row_to_dict(self.db.query_one("SELECT * FROM workspaces WHERE id = ?", (goal["workspace_id"],)))
        snapshot_now = self.evidence.snapshot_workspace(workspace["windows_path"])
        snapshot_ref = _snapshot_ref(snapshot_now)
        try:
            adapter = self._get_adapter(goal, session_row)
            avail = adapter.availability()
            if avail["status"] != "PASS":
                append_event(
                    self.db, type_="system.note",
                    payload={"note": f"review skipped: sol adapter unavailable ({avail['detail']})"},
                    goal_id=goal_id, run_id=run_id,
                )
                return
            adapter.ensure_thread(
                model=session_row["model"], effort=session_row["reasoning_effort"], cwd=workspace["windows_path"]
            )
            prompt = prompts.build_review_prompt(
                dict(goal), criteria, plan["content_md"] if plan else "", result, evidence, snapshot_ref,
                versions={
                    "goal_version": goal["goal_version"],
                    "plan_version": goal["plan_version"],
                    "acceptance_version": goal["acceptance_version"],
                },
            )
            cb = self._make_callbacks(goal=goal, run_row=run, session_row=session_row)
            outcome = self._turn_with_schema(adapter, prompt, prompts.REVIEW_OUTPUT_SCHEMA, cb)
            if outcome.status != "completed":
                append_event(
                    self.db, type_="system.note",
                    payload={"note": f"review turn {outcome.status}: {outcome.error or ''}"},
                    goal_id=goal_id, run_id=run_id,
                )
                return
            try:
                review_json = _extract_json(outcome.final_message)
            except ValueError as exc:
                append_event(
                    self.db, type_="system.note",
                    payload={"note": f"review output not valid JSON: {exc}"},
                    goal_id=goal_id, run_id=run_id,
                )
                return
            self._store_and_apply_review(
                goal=goal, run=run, result=result, evidence=evidence, criteria=criteria,
                review_json=review_json, snapshot_ref=snapshot_ref, snapshot_now=snapshot_now,
                workspace_path=workspace["windows_path"], is_auto=is_auto,
            )
        except Exception as exc:  # noqa: BLE001
            append_event(
                self.db, type_="system.note",
                payload={"note": f"review error: {exc}"}, goal_id=goal_id, run_id=run_id,
            )

    def _store_and_apply_review(
        self, *, goal, run, result, evidence, criteria, review_json, snapshot_ref, snapshot_now, workspace_path, is_auto
    ) -> None:
        goal_id = goal["id"]
        evidence_ids = {e["id"] for e in evidence}
        valid_verdicts = []
        for v in review_json.get("verdicts") or []:
            cited = [eid for eid in (v.get("evidence_ids") or []) if eid in evidence_ids]
            status = v.get("status")
            reason = v.get("reason") or ""
            if status == "PASS" and not cited:
                status = "UNKNOWN"
                reason = (reason + "（程序校验：PASS 未引用本轮有效证据，降级为 UNKNOWN）").strip()
            valid_verdicts.append(
                {
                    "criterion_id": v.get("criterion_id"),
                    "status": status,
                    "evidence_ids": cited,
                    "reason": reason,
                }
            )
        review_id = new_id("rev")
        overall = review_json.get("overall") or "UNKNOWN"
        next_action = review_json.get("next_action") or "request_user"

        with self.db.write() as conn:
            conn.execute(
                """INSERT INTO reviews(id, goal_id, run_id, result_id, mode, plan_version, acceptance_version,
                   goal_version, code_snapshot_ref, verdicts_json, overall, next_action, note, applied,
                   applied_action, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?)""",
                (
                    review_id, goal_id, run["id"], result.get("id") if result else None, goal["mode"],
                    int(goal["plan_version"]), int(goal["acceptance_version"]), int(goal["goal_version"]),
                    snapshot_ref, json.dumps(valid_verdicts, ensure_ascii=False), overall, next_action,
                    review_json.get("note") or "", now_iso(),
                ),
            )
            append_event(
                self.db, type_="review.created",
                payload={"review_id": review_id, "overall": overall, "next_action": next_action,
                         "verdicts": valid_verdicts},
                workspace_id=goal["workspace_id"], goal_id=goal_id, run_id=run["id"], conn=conn,
            )
        self.bus.notify()
        self._apply_review(
            goal=goal, run=run, review_id=review_id, valid_verdicts=valid_verdicts,
            overall=overall, next_action=next_action, review_json=review_json,
            snapshot_ref=snapshot_ref, snapshot_now=snapshot_now, criteria=criteria, is_auto=is_auto,
        )

    def _apply_review(
        self, *, goal, run, review_id, valid_verdicts, overall, next_action, review_json,
        snapshot_ref, snapshot_now, criteria, is_auto,
    ) -> None:
        """Python decides. The model's suggestion is input, not authority."""
        goal_id = goal["id"]
        required = [c for c in criteria if c["required"]]
        by_key = {v["criterion_id"]: v for v in valid_verdicts}
        all_required_pass = bool(required) and all(
            by_key.get(c["criterion_key"], {}).get("status") == "PASS" for c in required
        )
        # Recompute the workspace snapshot at apply time: a review made against
        # an older snapshot must not complete a changed working tree.
        workspace_row = self.db.query_one(
            "SELECT windows_path FROM workspaces WHERE id = ?", (goal["workspace_id"],)
        )
        snapshot_at_apply = (
            self.evidence.snapshot_workspace(workspace_row["windows_path"]) if workspace_row else {}
        )
        snapshot_consistent = _snapshot_ref(snapshot_at_apply) == snapshot_ref
        versions_valid = (
            int(goal["plan_version"]) == int(self.get_goal_row(goal_id)["plan_version"])
            and int(goal["acceptance_version"]) == int(self.get_goal_row(goal_id)["acceptance_version"])
        )
        applied_action = None
        note_extra = ""
        if all_required_pass and snapshot_consistent and versions_valid:
            applied_action = "completed"
            with self.db.write() as conn:
                conn.execute(
                    "UPDATE reviews SET applied=1, applied_action='completed' WHERE id=?", (review_id,)
                )
                conn.execute(
                    """UPDATE goals SET status='COMPLETED', stage='done', completion_note=?,
                       updated_at=? WHERE id=?""",
                    ("全部必需验收项通过且证据/快照一致。", now_iso(), goal_id),
                )
                append_event(
                    self.db, type_="review.applied",
                    payload={"review_id": review_id, "action": "completed"},
                    workspace_id=goal["workspace_id"], goal_id=goal_id, run_id=run["id"], conn=conn,
                )
                append_event(
                    self.db, type_="goal.completed", payload={"review_id": review_id},
                    workspace_id=goal["workspace_id"], goal_id=goal_id, conn=conn,
                )
        elif all_required_pass and not snapshot_consistent:
            applied_action = "blocked_snapshot_drift"
            note_extra = "程序校验：工作目录快照在验收采集后发生变化，不能应用完成；需重新执行并采集证据。"
        elif next_action in ("fix", "replan"):
            applied_action = "replan"
            fix_task = review_json.get("next_task") or {
                "title": "按验收意见修复",
                "instructions": review_json.get("note") or "修复未通过项后重新验证。",
                "verify_commands": [["{python}", "-m", "pytest", "-q"]],
            }
            fix_plan = {
                "summary": review_json.get("note") or "根据验收意见生成修复计划",
                "acceptance": [{"key": c["criterion_key"], "text": c["text"], "required": bool(c["required"])} for c in criteria],
                "tasks": [fix_task],
                "notes": "revision auto-generated from review",
            }
            self._apply_plan(
                goal_id, fix_plan,
                reason=f"review {review_id}: {next_action}", created_by="sol-review",
            )
            with self.db.write() as conn:
                conn.execute(
                    "UPDATE reviews SET applied=1, applied_action='replan' WHERE id=?", (review_id,)
                )
                append_event(
                    self.db, type_="review.applied",
                    payload={"review_id": review_id, "action": "replan", "reason": next_action},
                    workspace_id=goal["workspace_id"], goal_id=goal_id, run_id=run["id"], conn=conn,
                )
        elif next_action == "request_user" or overall in ("UNKNOWN", "BLOCKED"):
            applied_action = "paused_waiting_user"
            note_extra = "验收未能给出可自动执行的下一步，等待用户决定。"
        else:
            applied_action = "paused"
            note_extra = "验收结论不足以自动推进，等待用户决定。"

        if applied_action and applied_action != "completed" and applied_action != "replan":
            if applied_action == "blocked_snapshot_drift":
                new_status, stage = "READY", "snapshot_drift"
            else:
                new_status, stage = "PAUSED", "awaiting_user"
            with self.db.write() as conn:
                conn.execute(
                    "UPDATE reviews SET applied=1, applied_action=? WHERE id=?", (applied_action, review_id)
                )
                conn.execute(
                    "UPDATE goals SET status=?, stage=?, completion_note=?, updated_at=? WHERE id=?",
                    (new_status, stage, note_extra[:500], now_iso(), goal_id),
                )
                append_event(
                    self.db, type_="review.applied",
                    payload={"review_id": review_id, "action": applied_action, "note": note_extra},
                    workspace_id=goal["workspace_id"], goal_id=goal_id, run_id=run["id"], conn=conn,
                )
        self.bus.notify()
        self.budget.maybe_close_on_threshold(goal_id)

        # auto-advance: after a fix-plan revision, start the next run if allowed.
        # User already started this goal; auto_advance pushes within frozen
        # criteria/authorization/budget until complete or a user decision is needed.
        goal_now = self.get_goal_row(goal_id)
        if (
            applied_action == "replan"
            and goal_now["status"] == "READY"
            and int(goal_now["auto_advance"]) == 1
        ):
            try:
                self.start_run_async(goal_id, is_auto=True)
            except (ConflictError, BudgetBlocked) as exc:
                with self.db.write() as conn:
                    conn.execute(
                        "UPDATE goals SET status='PAUSED', stage='auto_stop', completion_note=?, updated_at=? WHERE id=?",
                        (f"自动推进停止：{exc}", now_iso(), goal_id),
                    )
                    append_event(
                        self.db, type_="system.note",
                        payload={"note": f"auto advance stopped: {exc}"},
                        goal_id=goal_id, conn=conn,
                    )
                self.bus.notify()

    # ------------------------------------------------------------- controls
    def pause_goal(self, goal_id: str, note: str = "") -> dict:
        goal = self.get_goal_row(goal_id)
        if not goal:
            raise KeyError(goal_id)
        with self.db.write() as conn:
            conn.execute(
                "UPDATE goals SET status='PAUSED', stage='paused', completion_note=?, updated_at=? WHERE id=?",
                (note[:500], now_iso(), goal_id),
            )
            append_event(
                self.db, type_="goal.paused", payload={"note": note},
                workspace_id=goal["workspace_id"], goal_id=goal_id, conn=conn,
            )
        # cancel the currently active run of this goal, if any
        active = self.db.query_one(
            "SELECT id FROM runs WHERE goal_id=? AND status IN ('QUEUED','STARTING','RUNNING','STOP_REQUESTED') LIMIT 1",
            (goal_id,),
        )
        if active:
            self.cancel_run(active["id"], note="goal paused")
        self.bus.notify()
        return {"ok": True, "status": "PAUSED"}

    def resume_goal(self, goal_id: str, note: str = "") -> dict:
        goal = self.get_goal_row(goal_id)
        if not goal:
            raise KeyError(goal_id)
        if goal["status"] == "CANCELLED":
            raise ConflictError("cancelled goals cannot be resumed")
        summary = self.budget.usage_summary(goal_id)
        if summary["gate"] == "CLOSED":
            raise ConflictError("budget gate is CLOSED; resume requires budget.resume with an explicit note/adjustment")
        new_status = "READY"
        with self.db.write() as conn:
            conn.execute(
                "UPDATE goals SET status=?, stage='resumed', updated_at=? WHERE id=?",
                (new_status, now_iso(), goal_id),
            )
            append_event(
                self.db, type_="goal.resumed", payload={"note": note},
                workspace_id=goal["workspace_id"], goal_id=goal_id, conn=conn,
            )
        self.bus.notify()
        return {"ok": True, "status": new_status}

    def cancel_goal(self, goal_id: str, note: str = "") -> dict:
        goal = self.get_goal_row(goal_id)
        if not goal:
            raise KeyError(goal_id)
        active = self.db.query_one(
            "SELECT id FROM runs WHERE goal_id=? AND status IN ('QUEUED','STARTING','RUNNING','STOP_REQUESTED') LIMIT 1",
            (goal_id,),
        )
        with self.db.write() as conn:
            conn.execute(
                "UPDATE goals SET status='CANCELLED', stage='cancelled', completion_note=?, updated_at=? WHERE id=?",
                (note[:500], now_iso(), goal_id),
            )
            append_event(
                self.db, type_="goal.cancelled", payload={"note": note},
                workspace_id=goal["workspace_id"], goal_id=goal_id, conn=conn,
            )
        if active:
            self.cancel_run(active["id"], note="goal cancelled")
        self.bus.notify()
        return {"ok": True, "status": "CANCELLED"}

    def cancel_run(self, run_id: str, note: str = "") -> dict:
        run = row_to_dict(self.db.query_one("SELECT * FROM runs WHERE id = ?", (run_id,)))
        if not run:
            raise KeyError(run_id)
        if run["status"] not in ("QUEUED", "STARTING", "RUNNING", "STOP_REQUESTED"):
            return {"ok": True, "status": run["status"], "note": "run already finished"}
        goal = self.get_goal_row(run["goal_id"])
        with self.db.write() as conn:
            conn.execute("UPDATE runs SET status='STOP_REQUESTED' WHERE id=?", (run_id,))
            append_event(
                self.db, type_="run.interrupted",
                payload={"run_id": run_id, "stage": "stop_requested", "note": note},
                workspace_id=goal["workspace_id"], goal_id=goal["id"], run_id=run_id, conn=conn,
            )
        self.bus.notify()
        adapter = self._adapters.get(run["session_id"])
        if adapter is not None:
            try:
                adapter.interrupt()
            except Exception:
                pass
        return {"ok": True, "status": "STOP_REQUESTED"}

    # ------------------------------------------------------------ recovery
    def recover_after_restart(self) -> dict:
        """Runs at startup: recover state; never auto-redispatch; keep budget locks."""
        rows = self.db.query(
            "SELECT r.* FROM runs r WHERE r.status IN ('QUEUED','STARTING','RUNNING','STOP_REQUESTED')"
        )
        recovered = []
        for r in rows:
            with self.db.write() as conn:
                conn.execute(
                    """UPDATE runs SET status='INTERRUPTED', ended_at=?,
                       error_class='PROCESS_RESTART', summary_json=? WHERE id=?""",
                    (now_iso(), json.dumps({"note": "app restarted; process ownership unknown, verify native process"}, ensure_ascii=False), r["id"]),
                )
                append_event(
                    self.db, type_="run.recovered",
                    payload={"run_id": r["id"], "previous_status": r["status"],
                             "note": "marked INTERRUPTED after restart; not auto-redispatched"},
                    goal_id=r["goal_id"], run_id=r["id"], conn=conn,
                )
                conn.execute(
                    "UPDATE goals SET status='PAUSED', stage='recovered', completion_note=?, updated_at=? WHERE id=? AND status='ACTIVE'",
                    ("应用重启：未确认的原生执行被标记为 INTERRUPTED，未自动重发。", now_iso(), r["goal_id"]),
                )
            recovered.append(r["id"])
        if recovered:
            append_event(
                self.db, type_="system.recovered", payload={"interrupted_runs": recovered},
            )
        self.bus.notify()
        return {"recovered_runs": recovered}

    # =====================================================================
    # retry helpers used by API
    # =====================================================================
    def command_receipt(self, key: str) -> dict | None:
        row = self.db.query_one("SELECT * FROM command_receipts WHERE key = ?", (key,))
        if not row:
            return None
        return parse_json(row["response_json"], {})

    def store_receipt(self, key: str, endpoint: str, status: str, response: dict) -> None:
        with self.db.write() as conn:
            conn.execute(
                """INSERT INTO command_receipts(key, endpoint, status, response_json, created_at)
                   VALUES (?, ?, ?, ?, ?) ON CONFLICT(key) DO NOTHING""",
                (key, endpoint, status, json.dumps(response, ensure_ascii=False), now_iso()),
            )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _extract_json(text: str) -> dict:
    """Extract the last valid JSON object from a message (tolerates code fences)."""
    if not text:
        raise ValueError("empty message")
    candidates = []
    # strip markdown fences
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    candidates.extend(fenced)
    # brace scan: find balanced objects, take the last
    depth = 0
    start = None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    candidates.append(text[start : i + 1])
    for cand in reversed(candidates):
        try:
            obj = json.loads(cand)
            if isinstance(obj, dict):
                return obj
        except ValueError:
            continue
    raise ValueError("no valid JSON object found in message")


def _plan_to_markdown(plan_json: dict) -> str:
    lines = [f"## 计划摘要", plan_json.get("summary") or "", ""]
    lines.append("### 验收标准")
    for item in plan_json.get("acceptance") or []:
        req = "（必需）" if item.get("required", True) else "（可选）"
        lines.append(f"- {item.get('key')}: {item.get('text')} {req}")
    lines.append("")
    lines.append("### 步骤")
    for step in plan_json.get("steps") or []:
        lines.append(f"1. {step}")
    lines.append("")
    lines.append("### 任务")
    for t in plan_json.get("tasks") or []:
        lines.append(f"- **{t.get('title')}**：{t.get('instructions')}")
        if t.get("deliverable"):
            lines.append(f"  - 交付物：{t['deliverable']}")
        for argv in t.get("verify_commands") or []:
            lines.append(f"  - 验证：`{' '.join(argv)}`")
    if plan_json.get("notes"):
        lines.append("")
        lines.append(f"> {plan_json['notes']}")
    return "\n".join(lines)


def _snapshot_ref(snapshot: dict[str, dict]) -> str:
    import hashlib

    canonical = json.dumps(
        {k: v.get("sha256") for k, v in sorted(snapshot.items())}, ensure_ascii=False, separators=(",", ":")
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
