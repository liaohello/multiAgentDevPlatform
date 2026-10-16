"""Server-level acceptance evidence (A02/A07/A09/A14/A15) against the running workbench.

Usage: python scripts/run_acceptance.py [--port 8787]
Writes docs/reports/evidence/acceptance/server_acceptance.json (+ workflow reports).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import httpx  # noqa: E402

from app.config import settings  # noqa: E402


def load_token() -> str:
    return json.loads((settings.data_dir / "runtime.json").read_text(encoding="utf-8"))["token"]


def wait_goal(client, base, H, goal_id, *, want=("COMPLETED", "PAUSED", "READY"), timeout=240):
    t0 = time.time()
    while time.time() - t0 < timeout:
        b = client.get(f"{base}/api/goals/{goal_id}", headers=H).json()
        if b["goal"]["status"] in want:
            return b
        time.sleep(2)
    return client.get(f"{base}/api/goals/{goal_id}", headers=H).json()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    args = ap.parse_args()
    base = f"http://127.0.0.1:{args.port}"
    token = load_token()
    H = {"X-AgentProj-Token": token}
    ev: dict = {"base": base, "sections": {}}

    outdir = settings.project_root / "docs" / "reports" / "evidence" / "acceptance"
    outdir.mkdir(parents=True, exist_ok=True)

    with httpx.Client(timeout=180) as client:
        # ---------------- A02: adapter capability table ----------------------
        r = client.get(f"{base}/api/env/adapters", headers=H)
        ev["sections"]["A02_adapters"] = {"status": r.status_code, "body": r.json()}

        # ---------------- A15: boundary checks -------------------------------
        no_token = client.get(f"{base}/api/goals")
        wrong_token = client.get(f"{base}/api/goals", headers={"X-AgentProj-Token": "nope"})
        foreign_origin = client.get(f"{base}/api/goals", headers={**H, "Origin": "https://evil.example"})
        local_origin = client.get(f"{base}/api/goals", headers={**H, "Origin": "http://127.0.0.1:5173"})
        ev["sections"]["A15_boundary"] = {
            "no_token": no_token.status_code, "wrong_token": wrong_token.status_code,
            "foreign_origin": foreign_origin.status_code, "local_origin": local_origin.status_code,
        }

        # ---------------- A09: idempotent duplicate start --------------------
        r = client.post(f"{base}/api/goals", json={
            "title": "A09 幂等验证", "request": "实现 normalize_tags。",
            "mode": "simulation", "workspace_mode": "demo", "scenario": "demo", "auto_advance": False,
        }, headers=H)
        g9 = r.json()["goal"]["id"]
        client.post(f"{base}/api/goals/{g9}/plan", headers=H)
        wait_goal(client, base, H, g9, want=("READY",), timeout=60)
        hk = {**H, "Idempotency-Key": "acc-dup-001"}
        r1 = client.post(f"{base}/api/goals/{g9}/start", headers=hk)
        r2 = client.post(f"{base}/api/goals/{g9}/start", headers=hk)
        wait_goal(client, base, H, g9, want=("ACTIVE", "READY", "PAUSED", "COMPLETED"), timeout=120)
        b9 = client.get(f"{base}/api/goals/{g9}", headers=H).json()
        ev["sections"]["A09_idempotency"] = {
            "first": {"status": r1.status_code, "body": r1.json()},
            "second": {"status": r2.status_code, "body": r2.json()},
            "runs_count": len(b9["runs"]),
            "same_run": r1.json().get("run_id") == r2.json().get("run_id"),
            "goal_id": g9,
        }

        # ---------------- A07: budget 100% stop + explicit resume ------------
        r = client.post(f"{base}/api/goals", json={
            "title": "A07 预算停止验证", "request": "实现 normalize_tags。",
            "mode": "simulation", "workspace_mode": "demo", "scenario": "budget",
            "budget_tokens": 5000, "auto_advance": True,
        }, headers=H)
        g7 = r.json()["goal"]["id"]
        client.post(f"{base}/api/goals/{g7}/plan", headers=H)
        wait_goal(client, base, H, g7, want=("READY",), timeout=60)
        client.post(f"{base}/api/goals/{g7}/start", headers={**H, "Idempotency-Key": "acc-budget-1"})
        b7 = wait_goal(client, base, H, g7, want=("PAUSED", "COMPLETED"), timeout=120)
        blocked_start = client.post(f"{base}/api/goals/{g7}/start", headers=H)
        blocked_resume = client.post(f"{base}/api/goals/{g7}/resume", json={"note": "试恢复"}, headers=H)
        runs_before = len(b7["runs"])
        closed_events = [e for e in b7["events"] if e["type"] == "budget.closed"]
        ev["sections"]["A07_budget"] = {
            "goal_id": g7,
            "usage": b7["usage"],
            "goal_status": b7["goal"]["status"], "goal_stage": b7["goal"]["stage"],
            "completion_note": b7["goal"]["completion_note"],
            "blocked_start_status": blocked_start.status_code,
            "blocked_start_detail": blocked_start.json().get("detail"),
            "resume_without_budget_status": blocked_resume.status_code,
            "resume_without_budget_detail": blocked_resume.json().get("detail"),
            "budget_closed_events": [{"cause": e["payload"].get("cause"), "reason": e["payload"].get("reason")} for e in closed_events],
            "runs_before_resume": runs_before,
        }
        # explicit resume with adjusted budget -> complete the loop
        r = client.post(f"{base}/api/goals/{g7}/budget/resume",
                        json={"note": "用户批准：追加预算至 20000", "budget_tokens": 20000}, headers=H)
        r = client.post(f"{base}/api/goals/{g7}/resume", json={"note": "恢复"}, headers=H)
        r = client.post(f"{base}/api/goals/{g7}/review", headers={**H, "Idempotency-Key": "acc-budget-review-1"})
        b7b = wait_goal(client, base, H, g7, want=("COMPLETED", "PAUSED"), timeout=240)
        ev["sections"]["A07_budget"]["after_resume"] = {
            "goal_status": b7b["goal"]["status"],
            "runs": [{"id": r_["id"], "status": r_["status"], "result": (r_["result"] or {}).get("status")} for r_ in b7b["runs"]],
            "reviews": [{"overall": rv["overall"], "applied": rv["applied_action"]} for rv in b7b["reviews"]],
            "gate": b7b["usage"]["gate"],
            "budget_tokens": b7b["usage"]["budget_tokens"],
            "resumed_events": [e["payload"].get("note") for e in b7b["events"] if e["type"] == "budget.resumed"],
        }
        (outdir / "a07_budget_goal_bundle.json").write_text(json.dumps(b7b, ensure_ascii=False, indent=1), encoding="utf-8")

        # ---------------- A14: workflows on the budget goal ------------------
        wt: dict = {}
        r = client.post(f"{base}/api/goals/{g7}/optimize", json={"text": "帮我写个 normalize_tags，逗号分隔去空白去重"}, headers=H)
        wt["optimize"] = {"status": r.status_code, "report_id": r.json().get("report_id")}
        (outdir / "a14_optimize.md").write_text(r.json().get("markdown", ""), encoding="utf-8")
        r = client.post(f"{base}/api/goals/{g7}/postmortem", headers=H)
        wt["postmortem"] = {"status": r.status_code, "report_id": r.json().get("report_id")}
        (outdir / "a14_postmortem.md").write_text(r.json().get("markdown", ""), encoding="utf-8")
        r = client.post(f"{base}/api/goals/{g7}/token-audit", headers=H)
        wt["token_audit"] = {"status": r.status_code, "report_id": r.json().get("report_id")}
        (outdir / "a14_token_audit.md").write_text(r.json().get("markdown", ""), encoding="utf-8")
        reports = client.get(f"{base}/api/workflows/reports", params={"goal_id": g7}, headers=H).json()
        wt["reports_count"] = len(reports)
        ev["sections"]["A14_workflows"] = wt

    (outdir / "server_acceptance.json").write_text(json.dumps(ev, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(ev, ensure_ascii=False, indent=1)[:4000])
    print(f"\nevidence -> {outdir / 'server_acceptance.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
