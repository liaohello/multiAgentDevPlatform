"""Evidence collector rules + the 'cannot complete on mismatch' guard (A06)."""
from conftest import create_goal


def test_command_whitelist_and_snapshot_diff(env, tmp_path):
    ctx = env["ctx"]
    ec = ctx["evidence"]

    ok, _ = ec.validate_command(["python", "-m", "pytest", "-q"])
    assert ok
    bad, reason = ec.validate_command(["powershell", "-Command", "rm -rf /"])
    assert not bad and "not allowed" in reason
    bad2, reason2 = ec.validate_command(["python", "-c", "print(1) && echo x"])
    assert not bad2 and "metacharacter" in reason2

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.py").write_text("a=1\n", encoding="utf-8")
    before = ec.snapshot_workspace(str(ws))
    (ws / "a.py").write_text("a=2\n", encoding="utf-8")
    (ws / "b.py").write_text("b=1\n", encoding="utf-8")
    after = ec.snapshot_workspace(str(ws))
    diff = ec.diff_snapshots(before, after)
    kinds = {d["path"]: d["change"] for d in diff}
    assert kinds == {"a.py": "modified", "b.py": "added"}


def test_review_pass_with_wrong_snapshot_is_blocked(env):
    """Python must refuse completion when the snapshot doesn't match the review."""
    client, headers = env["client"], env["headers"]
    controller = env["ctx"]["controller"]
    db = env["ctx"]["db"]

    goal_id = create_goal(client, headers, auto_advance=False)
    client.post(f"/api/goals/{goal_id}/plan", headers=headers)
    client.post(f"/api/goals/{goal_id}/start", headers=headers)

    bundle = client.get(f"/api/goals/{goal_id}", headers=headers).json()
    goal = bundle["goal"]
    run = bundle["runs"][0]
    result = run["result"]
    evidence = run["evidence"]
    ev_ids = [e["id"] for e in evidence]

    # craft a PASS review whose snapshot_ref cannot match the workspace
    review_json = {
        "verdicts": [
            {"criterion_id": c["criterion_key"], "status": "PASS", "evidence_ids": ev_ids[:1], "reason": "crafted"}
            for c in bundle["criteria"] if c["required"]
        ],
        "overall": "PASS",
        "next_action": "complete",
        "note": "crafted pass",
    }
    from app.db import parse_json

    with db.write() as conn:
        conn.execute(
            """INSERT INTO reviews(id, goal_id, run_id, result_id, mode, plan_version, acceptance_version,
               goal_version, code_snapshot_ref, verdicts_json, overall, next_action, note, applied, created_at)
               VALUES ('rev_test', ?, ?, ?, ?, ?, ?, ?, 'sha256:deadbeef', '[]', 'PASS', 'complete', '', 0, datetime('now'))""",
            (goal_id, run["id"], result["id"], goal["mode"], goal["plan_version"],
             goal["acceptance_version"], goal["goal_version"]),
        )
    controller._apply_review(
        goal=db.query_one("SELECT * FROM goals WHERE id=?", (goal_id,)),
        run=run, review_id="rev_test",
        valid_verdicts=review_json["verdicts"], overall="PASS", next_action="complete",
        review_json=review_json, snapshot_ref="sha256:deadbeef",
        snapshot_now={}, criteria=bundle["criteria"], is_auto=False,
    )
    g = db.query_one("SELECT * FROM goals WHERE id=?", (goal_id,))
    assert g["status"] != "COMPLETED"
    assert g["status"] == "READY" and g["stage"] == "snapshot_drift"
    rv = db.query_one("SELECT * FROM reviews WHERE id='rev_test'")
    assert rv["applied_action"] == "blocked_snapshot_drift"


def test_pass_verdict_without_evidence_is_downgraded(env):
    client, headers = env["client"], env["headers"]
    controller = env["ctx"]["controller"]
    db = env["ctx"]["db"]

    goal_id = create_goal(client, headers, auto_advance=False)
    client.post(f"/api/goals/{goal_id}/plan", headers=headers)
    client.post(f"/api/goals/{goal_id}/start", headers=headers)
    bundle = client.get(f"/api/goals/{goal_id}", headers=headers).json()
    run = bundle["runs"][0]

    review_json = {
        "verdicts": [
            {"criterion_id": c["criterion_key"], "status": "PASS", "evidence_ids": [], "reason": "no evidence cited"}
            for c in bundle["criteria"]
        ],
        "overall": "PASS",
        "next_action": "complete",
    }
    # call the store+apply path; empty evidence_id lists must be downgraded
    from app.controller import _snapshot_ref

    snapshot = controller.evidence.snapshot_workspace(env["settings"].goals_dir.parent / "demo-workspace" / goal_id)
    controller._store_and_apply_review(
        goal=db.query_one("SELECT * FROM goals WHERE id=?", (goal_id,)),
        run=run, result=run["result"], evidence=run["evidence"], criteria=bundle["criteria"],
        review_json=review_json, snapshot_ref=_snapshot_ref(snapshot), snapshot_now=snapshot,
        workspace_path=str(env["settings"].demo_workspace / goal_id), is_auto=False,
    )
    reviews = db.query("SELECT * FROM reviews WHERE goal_id=?", (goal_id,))
    assert reviews, "review was not stored"
    import json as _json

    verdicts = _json.loads(reviews[-1]["verdicts_json"])
    assert all(v["status"] == "UNKNOWN" for v in verdicts)
    g = db.query_one("SELECT * FROM goals WHERE id=?", (goal_id,))
    assert g["status"] != "COMPLETED"
