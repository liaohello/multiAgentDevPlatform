"""Workspace wiki: metadata index, scoped body reads, explicit Markdown import.

Access rules (R04/R05/R06):
- metadata of the *current workspace* is listable;
- body text is only read inside the workspace root or an explicitly granted
  scope; cross-directory reads without authorization are denied and recorded
  (`wiki.denied`) — the denial happens before any content is read.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

from .config import Settings
from .db import Database, parse_json
from .events import EventBus, append_event
from .ids import new_id, now_iso

MD_SUFFIXES = {".md", ".markdown", ".txt"}
SCAN_EXCLUDE = {".git", ".venv", "node_modules", "__pycache__", ".agentproj"}


def _sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract_meta(text: str) -> dict:
    """Title from first heading; summary from first non-heading paragraph; tags from frontmatter."""
    title = None
    summary = ""
    tags: list[str] = []
    lines = text.splitlines()
    in_front = False
    body_started = False
    for i, raw in enumerate(lines):
        line = raw.strip()
        if i == 0 and line == "---":
            in_front = True
            continue
        if in_front:
            if line == "---":
                in_front = False
                continue
            if line.startswith("tags:"):
                tags = [t.strip(" []'\"") for t in re.split(r"[,\[\]]", line.split(":", 1)[1]) if t.strip()]
            continue
        if not title and line.startswith("#"):
            title = line.lstrip("#").strip()
            continue
        if title and not body_started and line and not line.startswith(("#", "-", "*", ">", "|")):
            summary = line
            body_started = True
    if not title:
        title = "（无标题）"
    return {"title": title, "summary": summary[:400], "tags": tags}


class WikiManager:
    def __init__(self, db: Database, bus: EventBus, settings: Settings) -> None:
        self.db = db
        self.bus = bus
        self.settings = settings

    # ------------------------------------------------------------- listing
    def list_entries(self, workspace_id: str) -> list[dict]:
        rows = self.db.query(
            "SELECT * FROM wiki_entries WHERE workspace_id = ? ORDER BY updated_at DESC", (workspace_id,)
        )
        out = []
        for r in rows:
            d = dict(r)
            d["tags"] = parse_json(d.pop("tags_json"), [])
            d["meta"] = parse_json(d.pop("meta_json"), {})
            out.append(d)
        return out

    # -------------------------------------------------------------- import
    def import_markdown(
        self, *, workspace_id: str, source_path: str, session_id: str | None = None,
        goal_id: str | None = None, note: str | None = None,
    ) -> dict:
        src = Path(source_path)
        if not src.is_file():
            raise FileNotFoundError(source_path)
        text = src.read_text(encoding="utf-8", errors="replace")
        digest = _sha256_text(text)
        stored = self.settings.imports_dir / f"{digest[7:19]}-{src.name}"
        if not stored.exists():
            shutil.copyfile(src, stored)
        rel = self.settings.to_stored_path(stored)
        meta = extract_meta(text)
        entry_id = new_id("wiki")
        with self.db.write() as conn:
            conn.execute(
                """INSERT INTO wiki_entries(id, workspace_id, rel_path, title, summary, tags_json,
                   source, content_hash, imported, scope, meta_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 'workspace', ?, ?, ?)""",
                (entry_id, workspace_id, rel, meta["title"], meta["summary"],
                 json.dumps(meta["tags"], ensure_ascii=False), str(src), digest,
                 json.dumps({"note": note or ""}, ensure_ascii=False), now_iso(), now_iso()),
            )
            conn.execute(
                """INSERT INTO imports(id, workspace_id, session_id, goal_id, source_path,
                   stored_rel_path, sha256, note, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (new_id("imp"), workspace_id, session_id, goal_id, str(src), rel, digest, note or "", now_iso()),
            )
            append_event(
                self.db, type_="wiki.imported",
                payload={"entry_id": entry_id, "source": str(src), "hash": digest,
                         "scope": "workspace", "session_id": session_id, "goal_id": goal_id},
                workspace_id=workspace_id, conn=conn,
            )
        self.bus.notify()
        return self._entry_row(entry_id)

    def scan_workspace_docs(self, workspace_id: str, subdir: str = ".") -> dict:
        """Explicit scan of the *current* workspace for md/txt metadata (no cross-dir)."""
        ws = self.db.query_one("SELECT * FROM workspaces WHERE id = ?", (workspace_id,))
        if not ws:
            raise KeyError(workspace_id)
        root = Path(ws["windows_path"]).resolve()
        target = (root / subdir).resolve()
        if not str(target).lower().startswith(str(root).lower()):
            raise PermissionError("scan target escapes workspace root")
        added = 0
        for p in sorted(target.rglob("*")):
            if p.suffix.lower() not in MD_SUFFIXES or not p.is_file():
                continue
            if any(part in SCAN_EXCLUDE for part in p.parts):
                continue
            rel_to_root = str(p.relative_to(root)).replace("\\", "/")
            existing = self.db.query_one(
                "SELECT id, content_hash FROM wiki_entries WHERE workspace_id = ? AND rel_path = ?",
                (workspace_id, rel_to_root),
            )
            text = p.read_text(encoding="utf-8", errors="replace")
            digest = _sha256_text(text)
            if existing and existing["content_hash"] == digest:
                continue
            meta = extract_meta(text)
            if existing:
                with self.db.write() as conn:
                    conn.execute(
                        """UPDATE wiki_entries SET title=?, summary=?, tags_json=?, content_hash=?,
                           updated_at=? WHERE id=?""",
                        (meta["title"], meta["summary"], json.dumps(meta["tags"], ensure_ascii=False),
                         digest, now_iso(), existing["id"]),
                    )
            else:
                with self.db.write() as conn:
                    conn.execute(
                        """INSERT INTO wiki_entries(id, workspace_id, rel_path, title, summary, tags_json,
                           source, content_hash, imported, scope, meta_json, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 'workspace', '{}', ?, ?)""",
                        (new_id("wiki"), workspace_id, rel_to_root, meta["title"], meta["summary"],
                         json.dumps(meta["tags"], ensure_ascii=False), str(p), digest, now_iso(), now_iso()),
                    )
            added += 1
        self.bus.notify()
        return {"scanned": str(target), "entries_created_or_updated": added}

    # ------------------------------------------------------------ body read
    def read_body(self, entry_id: str, *, requester_workspace_id: str | None = None) -> dict:
        entry = self._entry_row(entry_id)
        if not entry:
            raise KeyError(entry_id)
        if requester_workspace_id and entry["workspace_id"] != requester_workspace_id:
            self._deny(
                entry["workspace_id"], f"cross-workspace body read denied: entry {entry_id} "
                f"belongs to {entry['workspace_id']}, requester is {requester_workspace_id}"
            )
            raise PermissionError("cross-workspace body read requires explicit authorization")
        path = self.settings.resolve_stored_path(entry["rel_path"])
        if not path.is_file():
            raise FileNotFoundError(entry["rel_path"])
        body = path.read_text(encoding="utf-8", errors="replace")
        append_event(
            self.db, type_="wiki.body_read",
            payload={"entry_id": entry_id, "rel_path": entry["rel_path"], "bytes": len(body)},
            workspace_id=entry["workspace_id"],
        )
        return {"entry": entry, "body": body}

    def read_workspace_path(self, workspace_id: str, rel_path: str) -> dict:
        """Read a file inside an authorized workspace root; deny anything else."""
        ws = self.db.query_one("SELECT * FROM workspaces WHERE id = ?", (workspace_id,))
        if not ws:
            raise KeyError(workspace_id)
        root = Path(ws["windows_path"]).resolve()
        target = (root / rel_path).resolve()
        if not str(target).lower().startswith(str(root).lower()):
            self._deny(workspace_id, f"path escapes workspace root: {rel_path}")
            raise PermissionError("path outside the authorized workspace scope")
        if not target.is_file():
            raise FileNotFoundError(rel_path)
        body = target.read_text(encoding="utf-8", errors="replace")
        append_event(
            self.db, type_="wiki.body_read",
            payload={"rel_path": rel_path, "bytes": len(body), "scope": "workspace"},
            workspace_id=workspace_id,
        )
        return {"rel_path": rel_path, "body": body}

    def _deny(self, workspace_id: str | None, reason: str) -> None:
        append_event(
            self.db, type_="wiki.denied", payload={"reason": reason}, workspace_id=workspace_id,
        )
        self.bus.notify()

    def _entry_row(self, entry_id: str) -> dict | None:
        row = self.db.query_one("SELECT * FROM wiki_entries WHERE id = ?", (entry_id,))
        if not row:
            return None
        d = dict(row)
        d["tags"] = parse_json(d.pop("tags_json"), [])
        d["meta"] = parse_json(d.pop("meta_json"), {})
        return d
