"""Adapter interfaces shared by real (Codex app-server) and fake/simulation roles.

An adapter only transports turns and streams normalized events. It never
changes goal state, budget or permissions: that is the controller's job.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol


class AdapterUnavailable(Exception):
    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


@dataclass
class TurnOutcome:
    thread_id: str
    turn_id: Optional[str]
    status: str  # completed | interrupted | failed | timeout | error
    final_message: str = ""
    error: Optional[str] = None
    usage_seen: bool = False
    duration_ms: Optional[int] = None


@dataclass
class TurnCallbacks:
    """Callbacks invoked from the adapter's reader thread.

    on_delta: transient display text (kind: message|command|status)
    on_product_event: allowed product event (type must be in ALLOWED_EVENT_TYPES)
    on_usage_total: normalized cumulative usage for the thread
    """

    on_delta: Callable[[str, str], None] = lambda kind, text: None
    on_product_event: Callable[[str, dict], None] = lambda type_, payload: None
    on_usage_total: Callable[[dict], None] = lambda snapshot: None


class AgentAdapterSession(Protocol):
    role: str
    session_id: str
    mode: str

    def availability(self) -> dict:
        """{'status': 'PASS'|'BLOCKED'|'FAIL', 'detail': str}"""

    def ensure_thread(
        self, *, model: str | None, effort: str | None, cwd: str | None, name: str | None = None
    ) -> str:
        """Create a new native thread (fresh session history) or resume the saved one."""

    def start_turn(
        self,
        prompt: str,
        *,
        output_schema: dict | None = None,
        effort: str | None = None,
        timeout: float | None = None,
        callbacks: TurnCallbacks | None = None,
    ) -> TurnOutcome: ...

    def interrupt(self) -> None: ...

    def close(self) -> None: ...

    @property
    def native_thread_id(self) -> str | None: ...


@dataclass
class FakeScriptContext:
    kind: str  # plan | review | worker | optimize | postmortem | token_audit
    goal: dict = field(default_factory=dict)
    task: dict = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)
