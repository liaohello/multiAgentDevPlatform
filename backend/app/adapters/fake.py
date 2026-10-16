"""Deterministic fake adapter (simulation mode).

Only the *external runtime* is replaced; the controller, budget, evidence
collector and persistence layers are the real ones. Simulation records are
tagged `mode=simulation` / `exactness=simulated` end to end.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

from .base import TurnCallbacks, TurnOutcome

CREATE_NO_WINDOW = 0x08000000


class FakeTurnContext:
    """Everything a fake handler may do. File edits and commands are REAL."""

    def __init__(
        self, *, role: str, session_id: str, thread_id: str, prompt: str,
        workspace_dir: str | None, stop_event: threading.Event | None = None,
    ):
        self.role = role
        self.session_id = session_id
        self.thread_id = thread_id
        self.prompt = prompt
        self.workspace_dir = workspace_dir
        self.deltas: list[tuple[str, str]] = []
        self.product_events: list[tuple[str, dict]] = []
        self.usages: list[dict] = []
        self.files_written: list[str] = []
        self.commands_run: list[dict] = []
        self._stop = stop_event if stop_event is not None else threading.Event()

    # ---- handler helpers ----
    def emit_delta(self, kind: str, text: str) -> None:
        self.deltas.append((kind, text))

    def emit_event(self, type_: str, payload: dict) -> None:
        self.product_events.append((type_, payload))

    def report_usage(self, breakdown: dict) -> None:
        self.usages.append(breakdown)

    def stop_requested(self) -> bool:
        return self._stop.is_set()

    def sleep(self, seconds: float) -> None:
        self._stop.wait(timeout=seconds)

    def write_file(self, rel_path: str, content: str) -> str:
        assert self.workspace_dir, "fake file ops require a workspace dir"
        target = Path(self.workspace_dir) / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self.files_written.append(rel_path)
        return str(target)

    def read_file(self, rel_path: str) -> str:
        assert self.workspace_dir
        return (Path(self.workspace_dir) / rel_path).read_text(encoding="utf-8")

    def run_command(self, argv: list[str], cwd: str | None = None, timeout: int = 300) -> dict:
        kwargs = {"capture_output": True, "text": True, "encoding": "utf-8", "errors": "replace"}
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = CREATE_NO_WINDOW
        proc = subprocess.run(argv, cwd=cwd or self.workspace_dir, timeout=timeout, **kwargs)
        record = {
            "argv": argv,
            "cwd": cwd or self.workspace_dir,
            "exit_code": proc.returncode,
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
        }
        self.commands_run.append(record)
        return record


class FakeAdapterSession:
    """Scripted session: logic comes from `handler(ctx) -> final_message`."""

    def __init__(
        self,
        *,
        session_id: str,
        role: str,
        handler: Callable[[FakeTurnContext], str],
        workspace_dir: str | None = None,
        mode: str = "simulation",
        step_delay: float | None = None,
    ) -> None:
        self.session_id = session_id
        self.role = role
        self.mode = mode
        self.handler = handler
        self.workspace_dir = workspace_dir
        self._native_thread_id: str | None = None
        self._stop = threading.Event()
        self._busy = threading.Event()
        self.step_delay = step_delay if step_delay is not None else float(os.environ.get("AGENTPROJ_FAKE_STEP_DELAY", "0.25"))

    # ------------------------------------------------ adapter protocol
    @property
    def native_thread_id(self) -> str | None:
        return self._native_thread_id

    def availability(self) -> dict:
        return {"status": "PASS", "detail": "deterministic fake adapter (simulation mode)"}

    def ensure_thread(self, *, model=None, effort=None, cwd=None, name=None) -> str:
        if self._native_thread_id is None:
            self._native_thread_id = f"fake-thread-{uuid.uuid4().hex[:12]}"
        return self._native_thread_id

    def start_turn(
        self,
        prompt: str,
        *,
        output_schema=None,
        effort=None,
        timeout=None,
        callbacks: TurnCallbacks | None = None,
    ) -> TurnOutcome:
        cb = callbacks or TurnCallbacks()
        assert self._native_thread_id, "ensure_thread first"
        self._stop.clear()
        self._busy.set()
        ctx = FakeTurnContext(
            role=self.role,
            session_id=self.session_id,
            thread_id=self._native_thread_id,
            prompt=prompt,
            workspace_dir=self.workspace_dir,
            stop_event=self._stop,
        )
        started = time.monotonic()
        try:
            cb.on_delta("status", f"fake turn started ({self.role})")
            if self.step_delay:
                ctx.sleep(self.step_delay)
            message = self.handler(ctx)
            for kind, text in ctx.deltas:
                cb.on_delta(kind, text)
            for type_, payload in ctx.product_events:
                cb.on_product_event(type_, payload)
            for usage in ctx.usages:
                cb.on_usage_total(usage)
            if ctx._stop.is_set():
                return TurnOutcome(
                    thread_id=self._native_thread_id,
                    turn_id=f"fake-turn-{uuid.uuid4().hex[:8]}",
                    status="interrupted",
                    final_message=message,
                    error="interrupted by request",
                    usage_seen=bool(ctx.usages),
                )
            return TurnOutcome(
                thread_id=self._native_thread_id,
                turn_id=f"fake-turn-{uuid.uuid4().hex[:8]}",
                status="completed",
                final_message=message,
                usage_seen=bool(ctx.usages),
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        finally:
            self._busy.clear()

    def interrupt(self) -> None:
        self._stop.set()

    def close(self) -> None:
        self._stop.set()
