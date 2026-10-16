"""Evidence collector: the only component that turns execution into verifiable facts.

The worker's natural-language claims are candidates only. This collector runs
whitelisted verification commands itself, records exit codes and outputs, and
snapshots the workspace so a later review can detect version/state mismatches.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable

from .config import Settings
from .db import Database
from .events import EventBus, append_event
from .ids import new_id, now_iso

CREATE_NO_WINDOW = 0x08000000

ALLOWED_PROGRAMS = {
    "python", "python.exe", "py", "pytest", "node", "npm", "npx", "git", "bash", "sh",
}

SNAPSHOT_EXCLUDE_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".agentproj", ".pytest_cache"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class EvidenceCollector:
    def __init__(self, db: Database, bus: EventBus, settings: Settings) -> None:
        self.db = db
        self.bus = bus
        self.settings = settings

    # ------------------------------------------------------------ snapshots
    def snapshot_workspace(self, workspace_path: str) -> dict[str, dict]:
        root = Path(workspace_path)
        out: dict[str, dict] = {}
        if not root.is_dir():
            return out
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SNAPSHOT_EXCLUDE_DIRS]
            for name in filenames:
                p = Path(dirpath) / name
                rel = str(p.relative_to(root)).replace("\\", "/")
                try:
                    out[rel] = {"sha256": sha256_file(p), "size": p.stat().st_size}
                except OSError:
                    continue
        return out

    @staticmethod
    def diff_snapshots(before: dict[str, dict], after: dict[str, dict]) -> list[dict]:
        changes = []
        for rel, meta in after.items():
            if rel not in before:
                changes.append({"path": rel, "change": "added", "sha256": meta["sha256"]})
            elif before[rel]["sha256"] != meta["sha256"]:
                changes.append({"path": rel, "change": "modified", "sha256": meta["sha256"]})
        for rel in before:
            if rel not in after:
                changes.append({"path": rel, "change": "deleted"})
        return sorted(changes, key=lambda c: c["path"])

    # -------------------------------------------------------------- commands
    def validate_command(self, argv: list[str]) -> tuple[bool, str]:
        if not argv or not isinstance(argv, list):
            return False, "empty command"
        prog = Path(argv[0]).name.lower()
        if prog not in ALLOWED_PROGRAMS:
            return False, f"program not allowed: {prog}"
        for arg in argv:
            if any(ch in str(arg) for ch in ("|", ">", "<", "&&", ";", "`", "$(")):
                return False, f"shell metacharacter rejected: {arg!r}"
        return True, ""

    def run_command(
        self, argv: list[str], cwd: str, *, timeout: int | None = None
    ) -> dict:
        timeout = timeout or self.settings.evidence_command_timeout_sec
        kwargs = {"capture_output": True, "text": True, "encoding": "utf-8", "errors": "replace", "timeout": timeout}
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = CREATE_NO_WINDOW
        started = time.monotonic()
        try:
            proc = subprocess.run(argv, cwd=cwd, **kwargs)
            return {
                "argv": argv,
                "cwd": cwd,
                "exit_code": proc.returncode,
                "stdout": proc.stdout or "",
                "stderr": proc.stderr or "",
                "duration_ms": int((time.monotonic() - started) * 1000),
                "timed_out": False,
            }
        except subprocess.TimeoutExpired as exc:
            return {
                "argv": argv,
                "cwd": cwd,
                "exit_code": None,
                "stdout": (exc.stdout or "") if isinstance(exc.stdout, str) else "",
                "stderr": f"timeout after {timeout}s",
                "duration_ms": int((time.monotonic() - started) * 1000),
                "timed_out": True,
            }
        except OSError as exc:
            return {
                "argv": argv,
                "cwd": cwd,
                "exit_code": None,
                "stdout": "",
                "stderr": f"failed to start: {exc}",
                "duration_ms": int((time.monotonic() - started) * 1000),
                "timed_out": False,
            }

    # ----------------------------------------------------------------- run
    def collect_for_run(
        self,
        *,
        goal: dict,
        run_id: str,
        workspace_id: str,
        workspace_path: str,
        before_snapshot: dict[str, dict],
        verify_commands: Iterable[list[str]],
        default_python: str | None = None,
    ) -> dict:
        """Runs verifications + snapshot; saves evidence files; returns summary."""
        goal_id = goal["id"]
        run_dir = self.settings.goals_dir / goal_id / "runs" / run_id / "evidence"
        run_dir.mkdir(parents=True, exist_ok=True)
        evidence_ids: list[str] = []
        tests: list[dict] = []

        py = default_python or sys.executable
        n = 0
        for raw_argv in verify_commands:
            argv = [a.replace("{python}", py) for a in raw_argv]
            n += 1
            ok, reason = self.validate_command(argv)
            if not ok:
                tests.append({"command": argv, "exit_code": None, "skipped_reason": reason})
                continue
            result = self.run_command(argv, workspace_path)
            out_text = (
                f"$ {' '.join(argv)}\n"
                f"cwd: {workspace_path}\n"
                f"exit_code: {result['exit_code']}\n"
                f"timed_out: {result['timed_out']}\n"
                f"duration_ms: {result['duration_ms']}\n"
                f"--- stdout ---\n{result['stdout']}\n--- stderr ---\n{result['stderr']}\n"
            )
            rel = self.settings.to_stored_path(
                self.settings.goals_dir / goal_id / "runs" / run_id / "evidence" / f"verify-{n}.log"
            )
            (self.settings.goals_dir / goal_id / "runs" / run_id / "evidence" / f"verify-{n}.log").write_text(
                out_text, encoding="utf-8"
            )
            ev_id = self._register(
                workspace_id=workspace_id,
                goal_id=goal_id,
                run_id=run_id,
                kind="command",
                rel_path=rel,
                meta={
                    "argv": argv,
                    "exit_code": result["exit_code"],
                    "timed_out": result["timed_out"],
                    "duration_ms": result["duration_ms"],
                },
            )
            evidence_ids.append(ev_id)
            tests.append(
                {
                    "command": argv,
                    "exit_code": result["exit_code"],
                    "timed_out": result["timed_out"],
                    "evidence_id": ev_id,
                    "summary_line": _pytest_summary(result["stdout"] + result["stderr"]),
                }
            )

        after_snapshot = self.snapshot_workspace(workspace_path)
        changes = self.diff_snapshots(before_snapshot, after_snapshot)
        snap_file = self.settings.goals_dir / goal_id / "runs" / run_id / "evidence" / "snapshot-after.json"
        snap_file.write_text(json.dumps(after_snapshot, ensure_ascii=False, indent=1), encoding="utf-8")
        snap_rel = self.settings.to_stored_path(snap_file)
        evidence_ids.append(
            self._register(
                workspace_id=workspace_id,
                goal_id=goal_id,
                run_id=run_id,
                kind="snapshot",
                rel_path=snap_rel,
                meta={"file_count": len(after_snapshot)},
            )
        )
        diff_file = self.settings.goals_dir / goal_id / "runs" / run_id / "evidence" / "changed-files.json"
        diff_file.write_text(json.dumps(changes, ensure_ascii=False, indent=1), encoding="utf-8")
        diff_rel = self.settings.to_stored_path(diff_file)
        if changes:
            evidence_ids.append(
                self._register(
                    workspace_id=workspace_id,
                    goal_id=goal_id,
                    run_id=run_id,
                    kind="diff",
                    rel_path=diff_rel,
                    meta={"changed": len(changes)},
                )
            )

        append_event(
            self.db,
            type_="evidence.collected",
            payload={"run_id": run_id, "tests": tests, "changed_files": len(changes), "evidence_ids": evidence_ids},
            workspace_id=workspace_id,
            goal_id=goal_id,
            run_id=run_id,
        )
        self.bus.notify()
        return {
            "evidence_ids": evidence_ids,
            "tests": tests,
            "changed_files": changes,
            "snapshot": after_snapshot,
        }

    def _register(
        self, *, workspace_id: str, goal_id: str, run_id: str, kind: str, rel_path: str, meta: dict
    ) -> str:
        ev_id = new_id("evd")
        full = self.settings.resolve_stored_path(rel_path)
        digest = sha256_file(full) if full.is_file() else None
        size = full.stat().st_size if full.is_file() else None
        with self.db.write() as conn:
            conn.execute(
                """INSERT INTO evidence(id, workspace_id, goal_id, run_id, kind, rel_path, sha256, size,
                   meta_json, collected_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ev_id,
                    workspace_id,
                    goal_id,
                    run_id,
                    kind,
                    rel_path,
                    digest,
                    size,
                    json.dumps(meta, ensure_ascii=False),
                    now_iso(),
                ),
            )
        return ev_id


def _pytest_summary(text: str) -> str | None:
    for line in reversed(text.splitlines()):
        low = line.lower()
        if ("passed" in low or "failed" in low or "error" in low) and "=" in line:
            return line.strip("= ").strip()
    return None
