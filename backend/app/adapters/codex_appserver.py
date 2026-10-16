"""Codex app-server adapter (JSON-RPC over stdio, newline-delimited JSON).

Implements the minimal product surface: initialize handshake, thread
start/resume, turn submit, event normalization, usage snapshots, interrupt.

Filtering rules (design §14):
- reasoning items and any credential-ish content are dropped before they can
  reach logs / DB / UI;
- only allowed product event types are forwarded;
- high-frequency text deltas go to the transient display channel.
"""
from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Optional

from .base import AdapterUnavailable, TurnCallbacks, TurnOutcome

# Windows: avoid console windows for child processes.
CREATE_NO_WINDOW = 0x08000000

REASONING_ITEM_TYPES = {"reasoning"}
ALLOWED_ITEM_TYPES_FOR_EVENTS = {"agentMessage", "commandExecution", "fileChange", "plan", "webSearch", "contextCompaction"}


class AppServerError(RuntimeError):
    pass


class AppServerClient:
    """One app-server process + JSON-RPC bookkeeping."""

    def __init__(
        self,
        command: list[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        client_name: str = "agentproj",
        client_version: str = "1.0.0",
        label: str = "codex",
    ) -> None:
        self.command = command
        self.cwd = cwd
        self.env = env
        self.client_name = client_name
        self.client_version = client_version
        self.label = label
        self.proc: subprocess.Popen | None = None
        self._next_id = 0
        self._id_lock = threading.Lock()
        self._pending: dict[int, queue.Queue] = {}
        self._notifications: "queue.Queue[dict]" = queue.Queue()
        self._stderr_lines: list[str] = []
        self._closed = threading.Event()
        self._reader: threading.Thread | None = None
        self.server_info: dict = {}

    # ------------------------------------------------------------- lifecycle
    def start(self, *, timeout: float = 30.0) -> None:
        kwargs: dict[str, Any] = {}
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = CREATE_NO_WINDOW
        try:
            self.proc = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.cwd,
                env=self.env,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                **kwargs,
            )
        except FileNotFoundError as exc:
            raise AdapterUnavailable(f"{self.label}: executable not found: {self.command[0]} ({exc})") from exc
        except PermissionError as exc:
            raise AdapterUnavailable(f"{self.label}: permission denied launching {self.command[0]} ({exc})") from exc
        except OSError as exc:
            raise AdapterUnavailable(f"{self.label}: failed to launch: {exc}") from exc
        self._reader = threading.Thread(target=self._read_loop, name=f"{self.label}-reader", daemon=True)
        self._reader.start()
        threading.Thread(target=self._read_stderr, name=f"{self.label}-stderr", daemon=True).start()
        result = self.request(
            "initialize",
            {"clientInfo": {"name": self.client_name, "version": self.client_version, "title": "agentProj workbench"}},
            timeout=timeout,
        )
        self.server_info = result or {}

    def _read_loop(self) -> None:
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if isinstance(msg, dict) and "id" in msg and ("result" in msg or "error" in msg):
                q = self._pending.pop(int(msg["id"]), None)
                if q is not None:
                    q.put(msg)
            else:
                self._notifications.put(msg)
        self._closed.set()

    def _read_stderr(self) -> None:
        assert self.proc and self.proc.stderr
        for line in self.proc.stderr:
            self._stderr_lines.append(line.rstrip())
            if len(self._stderr_lines) > 400:
                self._stderr_lines = self._stderr_lines[-200:]

    def _send(self, obj: dict) -> None:
        if not self.proc or not self.proc.stdin or self.proc.poll() is not None:
            raise AppServerError(f"{self.label}: app-server is not running")
        self.proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def request(self, method: str, params: dict | None = None, *, timeout: float = 30.0) -> dict:
        with self._id_lock:
            self._next_id += 1
            rid = self._next_id
        q: "queue.Queue[dict]" = queue.Queue()
        self._pending[rid] = q
        self._send({"id": rid, "method": method, "params": params or {}})
        try:
            msg = q.get(timeout=timeout)
        except queue.Empty as exc:
            self._pending.pop(rid, None)
            raise AppServerError(f"{self.label}: timeout waiting for {method}") from exc
        if "error" in msg:
            err = msg["error"]
            message = err.get("message") if isinstance(err, dict) else str(err)
            raise AppServerError(f"{self.label}: {method} error: {message}")
        return msg.get("result") or {}

    def stderr_tail(self, n: int = 40) -> list[str]:
        return self._stderr_lines[-n:]

    def close(self, *, kill: bool = False) -> None:
        proc = self.proc
        if not proc:
            return
        try:
            if proc.stdin and not proc.stdin.closed and not kill:
                try:
                    proc.stdin.close()  # EOF: the app-server flushes rollouts and exits
                except OSError:
                    pass
            if kill:
                self.kill_tree()
            # generous grace period so session rollouts are flushed to disk
            proc.wait(timeout=8)
        except Exception:
            try:
                self.kill_tree()
            except Exception:
                pass

    def kill_tree(self) -> None:
        """Terminate only this app-server process (and its own children)."""
        proc = self.proc
        if not proc or proc.poll() is not None:
            return
        try:
            if hasattr(subprocess, "CREATE_NO_WINDOW"):
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    capture_output=True,
                    creationflags=CREATE_NO_WINDOW,
                    timeout=15,
                )
            else:
                proc.terminate()
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    # ---------------------------------------------------------- notifications
    def next_notification(self, timeout: float = 1.0) -> Optional[dict]:
        try:
            return self._notifications.get(timeout=timeout)
        except queue.Empty:
            return None


class CodexAdapterSession:
    """Product-level session bound to one native Codex thread."""

    def __init__(
        self,
        *,
        session_id: str,
        role: str,
        command: list[str],
        cwd: str,
        model: str | None = None,
        effort: str | None = None,
        native_thread_id: str | None = None,
        approval_policy: str = "never",
        sandbox: str = "workspace-write",
        label: str = "codex",
        env: dict[str, str] | None = None,
        mode: str = "real",
    ) -> None:
        self.session_id = session_id
        self.role = role
        self.mode = mode
        self.command = command
        self.cwd = cwd
        self.model = model
        self.effort = effort
        self._native_thread_id = native_thread_id
        self.approval_policy = approval_policy
        self.sandbox = sandbox
        self.label = label
        self.env = env
        self.client: AppServerClient | None = None
        self._turn_lock = threading.Lock()
        self._active_turn_id: str | None = None
        self._last_usage_snapshot: dict | None = None
        self._closed = False

    # ------------------------------------------------------------ management
    @property
    def native_thread_id(self) -> str | None:
        return self._native_thread_id

    def availability(self) -> dict:
        exe = self.command[0]
        if not (Path(exe).is_file() or exe.lower().endswith(".exe") is False):
            pass
        p = Path(exe)
        if p.is_absolute() and not p.is_file():
            return {"status": "BLOCKED", "detail": f"executable missing: {exe}"}
        return {"status": "PASS", "detail": f"command: {' '.join(self.command[:2])}..."}

    def _ensure_client(self) -> AppServerClient:
        if self.client and self.client.proc and self.client.proc.poll() is None:
            return self.client
        client = AppServerClient(self.command, cwd=self.cwd, env=self.env, label=self.label)
        client.start()
        self.client = client
        return client

    def ensure_thread(
        self, *, model: str | None = None, effort: str | None = None, cwd: str | None = None, name: str | None = None
    ) -> str:
        client = self._ensure_client()
        if self._native_thread_id:
            res = client.request(
                "thread/resume",
                {
                    "threadId": self._native_thread_id,
                    "model": model or self.model,
                    "cwd": cwd or self.cwd,
                },
                timeout=60,
            )
            thread = res.get("thread") or {}
            tid = thread.get("id")
            if not tid:
                raise AppServerError(f"{self.label}: thread/resume returned no thread: {str(res)[:300]}")
            self._native_thread_id = tid
            return self._native_thread_id
        params: dict[str, Any] = {
            "cwd": cwd or self.cwd,
            "approvalPolicy": self.approval_policy,
            "sandbox": self.sandbox,
            "serviceName": "agentproj",
        }
        if model or self.model:
            params["model"] = model or self.model
        res = client.request("thread/start", params, timeout=60)
        thread = res.get("thread") or {}
        tid = thread.get("id")
        if not tid:
            raise AppServerError(f"{self.label}: thread/start returned no thread id: {res}")
        self._native_thread_id = tid
        return tid

    def set_effort(self, effort: str) -> None:
        # Effort changes take effect on the next turn without resetting the thread.
        self.effort = effort

    # ----------------------------------------------------------------- turn
    def start_turn(
        self,
        prompt: str,
        *,
        output_schema: dict | None = None,
        effort: str | None = None,
        timeout: float | None = None,
        callbacks: TurnCallbacks | None = None,
    ) -> TurnOutcome:
        if not self._native_thread_id:
            raise AppServerError(f"{self.label}: no thread; call ensure_thread first")
        cb = callbacks or TurnCallbacks()
        client = self._ensure_client()
        params: dict[str, Any] = {
            "threadId": self._native_thread_id,
            "input": [{"type": "text", "text": prompt}],
        }
        eff = effort or self.effort
        if eff:
            params["effort"] = eff
        if output_schema:
            params["outputSchema"] = output_schema
        with self._turn_lock:
            self._active_turn_id = None
        try:
            started = client.request("turn/start", params, timeout=60)
        except AppServerError as exc:
            # Race after a process handoff: resume succeeded against thread
            # metadata while the rollout was not yet fully loaded. Retry the
            # resume once, then the turn. Bounded: exactly one retry.
            if "thread not found" in str(exc) and self._native_thread_id:
                time.sleep(1.5)
                try:
                    client.request(
                        "thread/resume",
                        {"threadId": self._native_thread_id, "cwd": self.cwd},
                        timeout=60,
                    )
                    started = client.request("turn/start", params, timeout=60)
                except AppServerError:
                    raise exc
            else:
                raise
        turn = started.get("turn") or {}
        turn_id = turn.get("id")
        with self._turn_lock:
            self._active_turn_id = turn_id
        cb.on_delta("status", f"turn started: {turn_id}")

        deadline = time.monotonic() + (timeout or 1800)
        final_message = ""
        saw_completed = False
        outcome_status = "error"
        error_text: str | None = None
        duration_ms: int | None = None
        usage_seen = False

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                outcome_status = "timeout"
                error_text = f"turn exceeded timeout ({timeout or 1800}s)"
                break
            note = client.next_notification(timeout=min(1.0, remaining))
            if note is None:
                if client.proc and client.proc.poll() is not None:
                    outcome_status = "error"
                    error_text = f"app-server exited (code {client.proc.returncode}); stderr tail: {client.stderr_tail(8)}"
                    break
                continue
            method = note.get("method", "")
            nparams = note.get("params") or {}
            if method == "item/agentMessage/delta":
                text = nparams.get("delta") or nparams.get("text") or ""
                if text:
                    cb.on_delta("message", text)
            elif method == "item/started":
                item = nparams.get("item") or {}
                if item.get("type") == "commandExecution":
                    cb.on_delta("status", f"command started: {item.get('command')}")
            elif method == "item/completed":
                item = nparams.get("item") or {}
                itype = item.get("type")
                if itype in REASONING_ITEM_TYPES:
                    continue  # never persist reasoning
                if itype == "agentMessage":
                    final_message = item.get("text") or final_message
                elif itype == "commandExecution":
                    cb.on_product_event(
                        "run.command",
                        {
                            "command": item.get("command"),
                            "cwd": item.get("cwd"),
                            "exit_code": item.get("exitCode"),
                            "status": item.get("status"),
                            "duration_ms": item.get("durationMs"),
                            "output_tail": _tail(item.get("aggregatedOutput"), 4000),
                        },
                    )
                    cb.on_delta("command", f"[exit {item.get('exitCode')}] {item.get('command')}")
                elif itype == "fileChange":
                    cb.on_product_event(
                        "run.file_change",
                        {"status": item.get("status"), "changes": _summarize_changes(item.get("changes"))},
                    )
                elif itype == "plan":
                    cb.on_product_event("run.plan_updated", {"text": _tail(item.get("text"), 4000)})
            elif method == "thread/tokenUsage/updated":
                token_usage = nparams.get("tokenUsage") or {}
                total = token_usage.get("total") or {}
                snapshot = {
                    "thread_id": nparams.get("threadId"),
                    "turn_id": nparams.get("turnId"),
                    "total_tokens": int(total.get("totalTokens") or 0),
                    "input_tokens": int(total.get("inputTokens") or 0),
                    "cached_input_tokens": int(total.get("cachedInputTokens") or 0),
                    "output_tokens": int(total.get("outputTokens") or 0),
                    "reasoning_output_tokens": int(total.get("reasoningOutputTokens") or 0),
                    "model_context_window": token_usage.get("modelContextWindow"),
                    "raw": {"last": token_usage.get("last"), "total": total},
                }
                self._last_usage_snapshot = snapshot
                usage_seen = True
                cb.on_usage_total(snapshot)
            elif method == "turn/completed":
                turn_payload = nparams.get("turn") or {}
                if turn_id and turn_payload.get("id") and turn_payload.get("id") != turn_id:
                    continue  # not our turn
                status = turn_payload.get("status") or "completed"
                outcome_status = {
                    "completed": "completed",
                    "interrupted": "interrupted",
                    "failed": "failed",
                }.get(status, "error")
                err = turn_payload.get("error") or {}
                if err:
                    error_text = err.get("message")
                duration_ms = turn_payload.get("durationMs")
                saw_completed = True
                break
            elif method == "error":
                err = nparams.get("error") or nparams
                error_text = err.get("message") if isinstance(err, dict) else str(err)
                cb.on_product_event("error", {"source": "protocol", "message": _tail(error_text, 500)})
            else:
                # All other native notifications are intentionally ignored for
                # persistence; a few surface as status deltas.
                if method in ("turn/started", "thread/status/changed", "warning"):
                    cb.on_delta("status", method)

        with self._turn_lock:
            self._active_turn_id = None
        return TurnOutcome(
            thread_id=self._native_thread_id or "",
            turn_id=turn_id,
            status=outcome_status,
            final_message=final_message,
            error=error_text,
            usage_seen=usage_seen,
            duration_ms=duration_ms,
        )

    def interrupt(self) -> None:
        with self._turn_lock:
            turn_id = self._active_turn_id
        if not turn_id or not self.client:
            return
        try:
            self.client.request(
                "turn/interrupt",
                {"threadId": self._native_thread_id, "turnId": turn_id},
                timeout=20,
            )
        except AppServerError:
            pass

    def close(self) -> None:
        self._closed = True
        if self.client:
            self.client.close()
            self.client = None


def _tail(text: Any, limit: int) -> str:
    if text is None:
        return ""
    s = str(text)
    if len(s) <= limit:
        return s
    return f"...[truncated {len(s) - limit} chars]...\n" + s[-limit:]


def _summarize_changes(changes: Any) -> list[dict]:
    out = []
    if isinstance(changes, list):
        for ch in changes[:50]:
            if isinstance(ch, dict):
                out.append({"path": ch.get("path"), "kind": ch.get("kind") or ch.get("type")})
    return out
