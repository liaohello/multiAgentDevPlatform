"""A03 live evidence: thread isolation, resume, effort switch (real Windows Sol).

Two modes:
  # fresh run (4 minimal turns): create two threads, remember/recall codeword
  python scripts/live_check_sessions.py

  # recover + continue an existing attempt (2 minimal turns):
  python scripts/live_check_sessions.py --thread-a <id> --thread-b <id>

Evidence is printed as JSON on stdout.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.adapters.base import TurnCallbacks  # noqa: E402
from app.adapters.codex_appserver import AppServerClient, CodexAdapterSession  # noqa: E402
from app.config import settings  # noqa: E402

WORKDIR = settings.data_dir / "devtools" / "live-sessions"
WORKDIR.mkdir(parents=True, exist_ok=True)


def make_adapter(session_id: str, native_thread_id: str | None = None, effort: str = "low") -> CodexAdapterSession:
    return CodexAdapterSession(
        session_id=session_id,
        role="sol",
        command=[settings.codex_bin, "app-server", "--listen", "stdio://"],
        cwd=str(WORKDIR),
        model=None,
        effort=effort,
        native_thread_id=native_thread_id,
        approval_policy="never",
        sandbox="read-only",
        label=f"live-{session_id}",
    )


def quiet_callbacks() -> TurnCallbacks:
    return TurnCallbacks(
        on_delta=lambda k, t: None,
        on_product_event=lambda t, p: None,
        on_usage_total=lambda s: None,
    )


def read_history(thread_id: str) -> list[dict]:
    """Developer-visible history via the app-server (no model call)."""
    client = AppServerClient([settings.codex_bin, "app-server", "--listen", "stdio://"], label="history")
    client.start()
    try:
        res = client.request("thread/turns/list", {"threadId": thread_id, "limit": 50}, timeout=30)
    finally:
        client.close()
    turns = res.get("data") or []
    history = []
    for turn in turns:
        entry = {"turn_id": turn.get("id"), "status": turn.get("status"), "agent_messages": [], "user_messages": []}
        for item in turn.get("items") or []:
            if item.get("type") == "agentMessage":
                entry["agent_messages"].append((item.get("text") or "").strip()[:200])
            elif item.get("type") == "userMessage":
                content = item.get("content") or []
                texts = [c.get("text", "") for c in content if isinstance(c, dict)]
                entry["user_messages"].append(" ".join(texts)[:120])
        history.append(entry)
    return history


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--thread-a", default=None)
    ap.add_argument("--thread-b", default=None)
    ap.add_argument("--history-only", action="store_true",
                    help="only collect T1/T2 history for existing threads (no model calls); "
                         "reads prior T3/T4 results from --reuse-evidence")
    ap.add_argument("--reuse-evidence", default=None, help="merge T3/T4 from a previous evidence file")
    args = ap.parse_args()

    evidence: dict = {"turns": []}
    prev_turns: list[dict] = []
    if args.reuse_evidence and Path(args.reuse_evidence).is_file():
        prev = json.loads(Path(args.reuse_evidence).read_text(encoding="utf-8"))
        prev_turns = prev.get("turns", [])

    thread_a = args.thread_a
    thread_b = args.thread_b

    if args.history_only:
        hist_a = read_history(thread_a)
        hist_b = read_history(thread_b)
        t1_msgs = [m for t in hist_a for m in t["agent_messages"]]
        t2_msgs = [m for t in hist_b for m in t["agent_messages"]]
        t1 = next((m for m in t1_msgs if "OK" in m.upper()), t1_msgs[0] if t1_msgs else "")
        t2 = next((m for m in t2_msgs if "UNKNOWN" in m.upper()), t2_msgs[0] if t2_msgs else "")
        evidence["turns"].append({"id": "T1-new-thread-A(history)", "thread_id": thread_a,
                                  "final_message": t1[:80], "turn_count": len(hist_a)})
        evidence["turns"].append({"id": "T2-new-thread-B(history)", "thread_id": thread_b,
                                  "final_message": t2[:80], "turn_count": len(hist_b),
                                  "isolation_ok": "UNKNOWN" in t2.upper()})
        evidence["history_a"] = hist_a
        evidence["history_b"] = hist_b
        # merge previously recorded T3/T4
        for t in prev_turns:
            if t["id"].startswith(("T3", "T4")):
                evidence["turns"].append(t)
        thread_b = thread_b or ""
        proceed = False
    elif not thread_a:
        # ---- fresh: T1 remembers, T2 (fresh thread) cannot recall -------------
        a = make_adapter("sess-a")
        thread_a = a.ensure_thread(model=None, effort="low", cwd=str(WORKDIR))
        out1 = a.start_turn("记住这个暗号：ALPHA-7。只回复 OK 两个字母。", effort="low", timeout=180, callbacks=quiet_callbacks())
        evidence["turns"].append({"id": "T1-new-thread-A", "thread_id": thread_a, "status": out1.status,
                                  "final_message": out1.final_message.strip()[:60]})
        b = make_adapter("sess-b")
        thread_b = b.ensure_thread(model=None, effort="low", cwd=str(WORKDIR))
        out2 = b.start_turn("我刚才告诉你的暗号是什么？如果你不知道，只回复 UNKNOWN。", effort="low", timeout=180, callbacks=quiet_callbacks())
        evidence["turns"].append({"id": "T2-new-thread-B", "thread_id": thread_b, "status": out2.status,
                                  "final_message": out2.final_message.strip()[:60],
                                  "isolation_ok": "UNKNOWN" in out2.final_message.upper()})
        a.close()
        b.close()
        time.sleep(3)  # allow rollout flush before handoff
    else:
        # ---- recover T1/T2 facts from persisted history ------------------------
        hist_a = read_history(thread_a)
        hist_b = read_history(thread_b)
        t1_msgs = [m for t in hist_a for m in t["agent_messages"]]
        t2_msgs = [m for t in hist_b for m in t["agent_messages"]]
        t1 = t1_msgs[-1] if t1_msgs else ""
        t2 = t2_msgs[-1] if t2_msgs else ""
        evidence["turns"].append({"id": "T1-new-thread-A(history)", "thread_id": thread_a, "final_message": t1[:80]})
        evidence["turns"].append({"id": "T2-new-thread-B(history)", "thread_id": thread_b, "final_message": t2[:80],
                                  "isolation_ok": "UNKNOWN" in t2.upper()})
        evidence["history_turns_a"] = len(hist_a)
        evidence["history_turns_b"] = len(hist_b)

    if not args.history_only:
        # ---- T3: resume thread A in a fresh process ------------------------------
        a2 = make_adapter("sess-a2", native_thread_id=thread_a)
        out3 = a2.start_turn("把你记住的暗号回复给我，只回复那一个词。", effort="low", timeout=180, callbacks=quiet_callbacks())
        evidence["turns"].append({"id": "T3-resume-A", "thread_id": thread_a, "status": out3.status,
                                  "final_message": out3.final_message.strip()[:60],
                                  "resume_ok": "ALPHA-7" in out3.final_message.upper().replace(" ", "")})

        # ---- T4: switch effort on the same thread; history must persist ----------
        a2.set_effort("medium")
        out4 = a2.start_turn("再确认一次暗号，只回复那一个词。", effort="medium", timeout=180, callbacks=quiet_callbacks())
        evidence["turns"].append({"id": "T4-effort-switch", "thread_id": thread_a, "effort_after": "medium",
                                  "status": out4.status, "final_message": out4.final_message.strip()[:60],
                                  "history_kept": "ALPHA-7" in out4.final_message.upper().replace(" ", "")})
        a2.close()

    def find(turn_id: str) -> dict:
        return next((t for t in evidence["turns"] if t["id"] == turn_id), {})

    checks = {
        "t1_completed_or_recorded": bool(find("T1-new-thread-A(history)").get("final_message") or find("T1-new-thread-A").get("status") == "completed"),
        "threads_distinct": thread_a != thread_b,
        "isolation_ok": find("T2-new-thread-B(history)").get("isolation_ok") or find("T2-new-thread-B").get("isolation_ok", False),
        "resume_ok": find("T3-resume-A").get("resume_ok", False),
        "history_kept_after_effort_switch": find("T4-effort-switch").get("history_kept", False),
    }
    evidence["checks"] = checks
    evidence["all_pass"] = all(checks.values())
    print(json.dumps(evidence, ensure_ascii=False, indent=1))
    return 0 if evidence["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
