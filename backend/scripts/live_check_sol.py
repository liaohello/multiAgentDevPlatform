"""Minimal live check for the Windows Sol adapter (E3 evidence).

Costs a tiny amount of real quota (one short turn, low effort). Run manually:
    python scripts/live_check_sol.py            # handshake + thread only (no model call)
    python scripts/live_check_sol.py --turn     # + one tiny turn
    python scripts/live_check_sol.py --turn --interrupt   # + interrupt experiment
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.adapters.base import TurnCallbacks  # noqa: E402
from app.adapters.codex_appserver import CodexAdapterSession  # noqa: E402
from app.config import settings  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--turn", action="store_true", help="run one tiny real turn")
    ap.add_argument("--prompt", default="Reply with exactly one word: PONG")
    ap.add_argument("--effort", default="low")
    ap.add_argument("--model", default=None)
    ap.add_argument("--interrupt", action="store_true", help="interrupt the turn after a few seconds")
    ap.add_argument("--interrupt-after", type=float, default=4.0)
    ap.add_argument("--resume-thread", default=None, help="resume this native thread id and re-run the prompt")
    args = ap.parse_args()

    workdir = settings.data_dir / "devtools" / "live-sol"
    workdir.mkdir(parents=True, exist_ok=True)

    adapter = CodexAdapterSession(
        session_id="live-sol",
        role="sol",
        command=[settings.codex_bin, "app-server", "--listen", "stdio://"],
        cwd=str(workdir),
        model=args.model,
        effort=args.effort,
        native_thread_id=args.resume_thread,
        approval_policy="never",
        sandbox="read-only",
        label="live-sol",
    )

    print("[1] start app-server + initialize …")
    t0 = time.time()
    tid = adapter.ensure_thread(model=args.model, effort=args.effort, cwd=str(workdir))
    print(f"    OK thread_id={tid} (client ready in {time.time()-t0:.1f}s)")

    if not args.turn:
        adapter.close()
        print("[done] handshake-only check passed (no model call made)")
        return 0

    deltas: list[str] = []
    events: list[tuple[str, dict]] = []
    usage: list[dict] = []
    cb = TurnCallbacks(
        on_delta=lambda kind, text: deltas.append(text),
        on_product_event=lambda type_, payload: events.append((type_, payload)),
        on_usage_total=lambda snapshot: usage.append(snapshot),
    )

    result_holder: dict = {}

    def run_turn():
        result_holder["outcome"] = adapter.start_turn(
            args.prompt, effort=args.effort, timeout=180, callbacks=cb
        )

    th = threading.Thread(target=run_turn)
    th.start()
    if args.interrupt:
        time.sleep(args.interrupt_after)
        print("[!] sending native interrupt …")
        adapter.interrupt()
    th.join(timeout=200)

    outcome = result_holder.get("outcome")
    print("[2] turn outcome:", outcome.status if outcome else "NO RESULT")
    if outcome:
        print("    final_message:", (outcome.final_message or "")[:300].replace("\n", " ") or "(empty)")
        print("    turn_id:", outcome.turn_id, "| duration_ms:", outcome.duration_ms)
        print("    error:", outcome.error)

    print("[3] transient deltas:", len(deltas), "chars:", sum(len(d) for d in deltas))
    print("[4] product events:", [e[0] for e in events])
    if usage:
        last = usage[-1]
        print("[5] usage snapshot: total_tokens =", last.get("total_tokens"),
              "input =", last.get("input_tokens"), "output =", last.get("output_tokens"),
              "reasoning =", last.get("reasoning_output_tokens"))

    adapter.close()
    summary = {
        "thread_id": tid,
        "turn_status": outcome.status if outcome else None,
        "turn_id": outcome.turn_id if outcome else None,
        "final_message": (outcome.final_message or "")[:500] if outcome else None,
        "usage_total_tokens": usage[-1].get("total_tokens") if usage else None,
        "interrupted": bool(args.interrupt),
    }
    print("[static] " + json.dumps(summary, ensure_ascii=False, default=str))
    return 0 if (outcome and outcome.status == "completed") or args.interrupt else 1


if __name__ == "__main__":
    raise SystemExit(main())
