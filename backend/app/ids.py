"""Sortable-ish short IDs with prefixes so relationships are readable."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"
