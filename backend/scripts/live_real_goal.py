"""A04: launch a REAL goal through the running workbench (browser-equivalent API path).

Real Windows Sol planning turn runs for real; the worker step goes through the
product's WSL adapter (expected BLOCKED in this environment). All state,
usage and events are recorded in the product database.

Usage:
    python scripts/live_real_goal.py [--port 8787]
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
from app.simulation import seed_demo_workspace  # noqa: E402


def load_token() -> str:
    runtime = settings.data_dir / "runtime.json"
    return json.loads(runtime.read_text(encoding="utf-8"))["token"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    args = ap.parse_args()
    base = f"http://127.0.0.1:{args.port}"
    token = load_token()
    H = {"X-AgentProj-Token": token}

    evidence: dict = {"base": base, "steps": []}

    # 1) prepare an isolated real demo workspace
    demo = settings.data_dir / "devtools" / "live-real-workspace"
    seed_demo_workspace(demo)
    evidence["workspace_path"] = str(demo)

    with httpx.Client(timeout=120) as client:
        # 2) register workspace
        r = client.post(f"{base}/api/workspaces", json={"name": "真实演示目录", "windows_path": str(demo)}, headers=H)
        ws = r.json()
        evidence["workspace"] = {"id": ws["id"], "wsl_path": ws["wsl_path"]}
        evidence["steps"].append({"step": "register-workspace", "status": r.status_code})

        # 3) create a REAL goal
        r = client.post(
            f"{base}/api/goals",
            json={
                "title": "真实闭环演示：实现 normalize_tags",
                "request": "实现 normalize_tags(text)：按逗号拆分、去首尾空白、忽略空项、去重并保留顺序。用标准库测试验证。",
                "mode": "real",
                "workspace_mode": "existing",
                "workspace_id": ws["id"],
                "budget_tokens": None,
                "auto_advance": True,
            },
            headers=H,
        )
        goal_id = r.json()["goal"]["id"]
        evidence["goal_id"] = goal_id
        evidence["steps"].append({"step": "create-real-goal", "status": r.status_code, "goal_id": goal_id})

        # 4) real planning turn (Sol on Windows)
        t0 = time.time()
        r = client.post(f"{base}/api/goals/{goal_id}/plan", headers={**H, "Idempotency-Key": "real-plan-1"})
        evidence["steps"].append({"step": "plan-accepted", "status": r.status_code, "body": r.json()})
        plan_state = None
        while time.time() - t0 < 300:
            time.sleep(3)
            b = client.get(f"{base}/api/goals/{goal_id}", headers=H).json()
            plan_state = b["goal"]["plan_version"]
            if plan_state >= 1 or b["goal"]["status"] == "PAUSED":
                break
        bundle = client.get(f"{base}/api/goals/{goal_id}", headers=H).json()
        evidence["after_plan"] = {
            "seconds": round(time.time() - t0, 1),
            "plan_version": bundle["goal"]["plan_version"],
            "status": bundle["goal"]["status"],
            "stage": bundle["goal"]["stage"],
            "usage": bundle["usage"]["used_tokens"],
            "plan_md": (bundle["plan"] or {}).get("content_md", "")[:1200],
            "criteria": [c["text"] for c in bundle["criteria"]],
        }
        evidence["steps"].append({
            "step": "plan-result",
            "plan_version": bundle["goal"]["plan_version"],
            "status": bundle["goal"]["status"],
        })

        # 5) start the run: worker adapter probes WSL (expected BLOCKED)
        if bundle["goal"]["plan_version"] >= 1:
            r = client.post(f"{base}/api/goals/{goal_id}/start", headers={**H, "Idempotency-Key": "real-start-1"})
            evidence["steps"].append({"step": "start-accepted", "status": r.status_code, "body": r.json()})
            t1 = time.time()
            while time.time() - t1 < 180:
                time.sleep(2)
                bundle = client.get(f"{base}/api/goals/{goal_id}", headers=H).json()
                runs = bundle["runs"]
                if runs and runs[-1]["status"] in ("SUCCEEDED", "FAILED", "INTERRUPTED"):
                    break
            bundle = client.get(f"{base}/api/goals/{goal_id}", headers=H).json()
            last_run = bundle["runs"][-1] if bundle["runs"] else None
            evidence["after_start"] = {
                "goal_status": bundle["goal"]["status"],
                "goal_stage": bundle["goal"]["stage"],
                "completion_note": bundle["goal"]["completion_note"],
                "run": {
                    "id": last_run["id"], "status": last_run["status"], "error_class": last_run["error_class"],
                    "summary": last_run["summary"],
                } if last_run else None,
                "usage": bundle["usage"],
            }

        # full raw bundle for the evidence file
        evidence["bundle"] = client.get(f"{base}/api/goals/{goal_id}", headers=H).json()

    out = settings.project_root / "docs" / "reports" / "evidence" / "a04" / "real_goal_attempt.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"evidence -> {out}")
    print(json.dumps({
        "goal_id": evidence.get("goal_id"),
        "after_plan": evidence.get("after_plan", {}).get("status"),
        "plan_version": evidence.get("after_plan", {}).get("plan_version"),
        "usage_after_plan": evidence.get("after_plan", {}).get("usage"),
        "after_start": evidence.get("after_start", {}).get("goal_status"),
        "run": evidence.get("after_start", {}).get("run"),
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
