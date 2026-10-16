"""Skill registry, project allow-list, session selection, version freezing.

Records are strictly staged: configured (selected) -> provided (frozen into a
run) -> loaded_observed (only when the runtime itself reports the skill), and
`unknown` when nothing can be observed. Configuration never implies invocation.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from .config import Settings
from .db import Database, parse_json
from .events import EventBus, append_event
from .ids import new_id, now_iso

BUILTIN_SKILLS = [
    {
        "id": "prompt-optimizer",
        "name": "Prompt Optimizer (Quick)",
        "version": "builtin-1",
        "description": "本地实现的 Quick 模式需求整理工作流（工作台内置）。",
        "source": "builtin",
        "license": "internal",
    },
    {
        "id": "goal-review",
        "name": "Goal Review",
        "version": "builtin-1",
        "description": "闭环中的逐项验收工作台内置工作流。",
        "source": "builtin",
        "license": "internal",
    },
    {
        "id": "goal-collaboration-postmortem",
        "name": "Goal Collaboration Postmortem",
        "version": "builtin-1",
        "description": "全链复盘工作台内置工作流。",
        "source": "builtin",
        "license": "internal",
    },
    {
        "id": "token-audit",
        "name": "Token Audit",
        "version": "builtin-1",
        "description": "用量诊断工作台内置工作流。",
        "source": "builtin",
        "license": "internal",
    },
]


def _hash_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


class SkillManager:
    def __init__(self, db: Database, bus: EventBus, settings: Settings) -> None:
        self.db = db
        self.bus = bus
        self.settings = settings

    # ------------------------------------------------------------- registry
    def seed_builtins(self) -> None:
        for s in BUILTIN_SKILLS:
            existing = self.db.query_one("SELECT id FROM skill_registry WHERE id = ?", (s["id"],))
            if existing:
                continue
            self._insert_entry(
                skill_id=s["id"], name=s["name"], version=s["version"], source=s["source"],
                rel_path=None, content=s["description"], license=s["license"], allowed=1,
            )

    def _insert_entry(
        self, *, skill_id: str, name: str, version: str, source: str, rel_path: str | None,
        content: str, license: str | None, allowed: int, meta: dict | None = None,
    ) -> None:
        ts = now_iso()
        with self.db.write() as conn:
            conn.execute(
                """INSERT INTO skill_registry(id, name, version, source, rel_path, content_hash,
                   license, status, allowed, meta_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'imported', ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name, version=excluded.version,
                     source=excluded.source, rel_path=excluded.rel_path, content_hash=excluded.content_hash,
                     license=excluded.license, allowed=excluded.allowed, meta_json=excluded.meta_json,
                     updated_at=excluded.updated_at""",
                (skill_id, name, version, source, rel_path, _hash_text(content), license, allowed,
                 json.dumps(meta or {}, ensure_ascii=False), ts, ts),
            )
            append_event(
                self.db, type_="skill.registry_updated",
                payload={"skill_id": skill_id, "version": version, "allowed": bool(allowed), "source": source},
                conn=conn,
            )
        self.bus.notify()

    def list_registry(self) -> list[dict]:
        rows = self.db.query("SELECT * FROM skill_registry ORDER BY id")
        return [dict(r) | {"allowed": bool(r["allowed"]), "meta": parse_json(r["meta_json"], {})} for r in rows]

    def get(self, skill_id: str) -> dict | None:
        row = self.db.query_one("SELECT * FROM skill_registry WHERE id = ?", (skill_id,))
        return dict(row) if row else None

    def set_allowed(self, skill_id: str, allowed: bool) -> dict:
        row = self.get(skill_id)
        if not row:
            raise KeyError(skill_id)
        with self.db.write() as conn:
            conn.execute(
                "UPDATE skill_registry SET allowed = ?, updated_at = ? WHERE id = ?",
                (1 if allowed else 0, now_iso(), skill_id),
            )
            append_event(
                self.db, type_="skill.allowed",
                payload={"skill_id": skill_id, "allowed": allowed}, conn=conn,
            )
        self.bus.notify()
        return {"ok": True, "skill_id": skill_id, "allowed": allowed}

    def import_local(self, source_path: str, *, skill_id: str | None = None) -> dict:
        src = Path(source_path)
        if not src.is_file():
            raise FileNotFoundError(source_path)
        content = src.read_text(encoding="utf-8")
        name = src.stem
        sid = skill_id or name.lower().replace(" ", "-")
        target_dir = self.settings.skills_dir / sid
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / src.name
        shutil.copyfile(src, target)
        rel = str(target.relative_to(self.settings.project_root)).replace("\\", "/")
        version = f"hash:{_hash_text(content)[7:19]}"
        self._insert_entry(
            skill_id=sid, name=name, version=version, source=str(src), rel_path=rel,
            content=content, license=None, allowed=0,
            meta={"imported_from": str(src), "size": len(content)},
        )
        return self.get(sid)

    # -------------------------------------------------------- session scope
    def select_for_session(self, session_id: str, skill_ids: list[str]) -> dict:
        session = self.db.query_one("SELECT * FROM sessions WHERE id = ?", (session_id,))
        if not session:
            raise KeyError(session_id)
        chosen = []
        for sid in skill_ids:
            entry = self.get(sid)
            if not entry:
                raise KeyError(f"skill not found: {sid}")
            if not entry["allowed"]:
                raise PermissionError(f"skill not allowed by project: {sid}")
            chosen.append(entry)
        with self.db.write() as conn:
            conn.execute("DELETE FROM session_skills WHERE session_id = ?", (session_id,))
            for entry in chosen:
                conn.execute(
                    """INSERT INTO session_skills(id, session_id, skill_id, version, content_hash, frozen_at, created_at)
                       VALUES (?, ?, ?, ?, ?, NULL, ?)""",
                    (new_id("ssk"), session_id, entry["id"], entry["version"], entry["content_hash"], now_iso()),
                )
            append_event(
                self.db, type_="skill.session_selected",
                payload={"session_id": session_id, "skills": [e["id"] for e in chosen]},
                session_id=session_id, workspace_id=session["workspace_id"], conn=conn,
            )
        self.bus.notify()
        return self.session_skills(session_id)

    def session_skills(self, session_id: str) -> list[dict]:
        rows = self.db.query("SELECT * FROM session_skills WHERE session_id = ? ORDER BY skill_id", (session_id,))
        return [dict(r) for r in rows]

    # --------------------------------------------------------- run freezing
    def freeze_for_run(self, run_id: str, session_id: str) -> list[dict]:
        """Record configured/provided states at run start (versions frozen)."""
        selected = self.session_skills(session_id)
        ts = now_iso()
        out = []
        with self.db.write() as conn:
            for s in selected:
                for state in ("configured", "provided"):
                    conn.execute(
                        """INSERT INTO skill_usage(id, run_id, skill_id, state, note, ts)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (new_id("sku"), run_id, s["skill_id"], state,
                         f"frozen version {s['version']} at run start", ts),
                    )
                conn.execute("UPDATE session_skills SET frozen_at = ? WHERE id = ?", (ts, s["id"]))
                append_event(
                    self.db, type_="skill.provided",
                    payload={"run_id": run_id, "skill_id": s["skill_id"], "version": s["version"]},
                    run_id=run_id, session_id=session_id, conn=conn,
                )
                out.append({"skill_id": s["skill_id"], "version": s["version"], "state": "provided"})
        self.bus.notify()
        return out

    def record_observed(self, run_id: str, session_id: str, visible_skill_ids: list[str]) -> dict:
        """Only call with runtime-reported evidence (e.g. skills/list output)."""
        selected = {s["skill_id"] for s in self.session_skills(session_id)}
        ts = now_iso()
        observed, missing = [], []
        with self.db.write() as conn:
            for sid in selected:
                if sid in visible_skill_ids:
                    conn.execute(
                        """INSERT INTO skill_usage(id, run_id, skill_id, state, note, ts)
                           VALUES (?, ?, ?, 'loaded_observed', ?, ?)""",
                        (new_id("sku"), run_id, sid, "runtime reported this skill as visible", ts),
                    )
                    append_event(
                        self.db, type_="skill.loaded_observed",
                        payload={"run_id": run_id, "skill_id": sid}, run_id=run_id, session_id=session_id, conn=conn,
                    )
                    observed.append(sid)
                else:
                    conn.execute(
                        """INSERT INTO skill_usage(id, run_id, skill_id, state, note, ts)
                           VALUES (?, ?, ?, 'unknown', ?, ?)""",
                        (new_id("sku"), run_id, sid, "not visible in runtime report; state unknown", ts),
                    )
                    missing.append(sid)
        self.bus.notify()
        return {"observed": observed, "unknown": missing}

    def usage_for_run(self, run_id: str) -> list[dict]:
        # insertion order matters (configured before provided); same-second ts is ambiguous
        rows = self.db.query("SELECT * FROM skill_usage WHERE run_id = ? ORDER BY rowid", (run_id,))
        return [dict(r) for r in rows]
