"""Idempotency, single-writer slot, cancel semantics, crash recovery."""
import time

from conftest import create_goal


def test_idempotent_start_same_key_same_run(env):
    client, headers = env["client"], env["headers"]
    goal_id = create_goal(client, headers, auto_advance=False)
    client.post(f"/api/goals/{goal_id}/plan", headers=headers)
    h = dict(headers)
    h["Idempotency-Key"] = "dup-key-1"
    r1 = client.post(f"/api/goals/{goal_id}/start", headers=h)
    r2 = client.post(f"/api/goals/{goal_id}/start", headers=h)
    assert r1.status_code == 200 and r2.status_code == 200
    body1, body2 = r1.json(), r2.json()
    assert body1["run_id"] == body2["run_id"]
    assert body2.get("duplicate") in (True,)
    bundle = client.get(f"/api/goals/{goal_id}", headers=headers).json()
    assert len(bundle["runs"]) == 1  # duplicate click did not create a second run


def test_single_writer_slot_and_cancel(env):
    """A long run occupies the workspace slot; cancel only affects that run."""
    client, headers = env["client"], env["headers"]
    controller = env["ctx"]["controller"]

    goal_id = create_goal(client, headers, scenario="cancel", auto_advance=False)
    client.post(f"/api/goals/{goal_id}/plan", headers=headers)  # sync plan
    controller.sync_mode = False  # now run the goal in the background so we can cancel it
    r = client.post(f"/api/goals/{goal_id}/start", headers=headers)
    assert r.status_code == 200
    run_id = r.json()["run_id"]

    # wait until RUNNING
    deadline = time.time() + 15
    status = None
    while time.time() < deadline:
        row = env["ctx"]["db"].query_one("SELECT status FROM runs WHERE id = ?", (run_id,))
        status = row["status"] if row else None
        if status == "RUNNING":
            break
        time.sleep(0.2)
    assert status == "RUNNING", status

    # second run in the same workspace is rejected (single writer)
    r2 = client.post(f"/api/goals/{goal_id}/start", headers=headers)
    assert r2.status_code == 409
    assert "active run" in r2.json()["detail"]

    # cancel: stop_requested then interrupted; no residue
    r3 = client.post(f"/api/runs/{run_id}/cancel", json={"note": "test cancel"}, headers=headers)
    assert r3.status_code == 200
    deadline = time.time() + 20
    while time.time() < deadline:
        row = env["ctx"]["db"].query_one("SELECT status FROM runs WHERE id = ?", (run_id,))
        if row["status"] in ("INTERRUPTED", "FAILED", "SUCCEEDED"):
            break
        time.sleep(0.2)
    assert row["status"] == "INTERRUPTED", row["status"]
    events = env["ctx"]["db"].query("SELECT type FROM events WHERE run_id = ?", (run_id,))
    types = [e["type"] for e in events]
    assert "run.interrupted" in types


def test_crash_recovery_marks_interrupted_and_never_redispatches(env):
    client, headers = env["client"], env["headers"]
    controller = env["ctx"]["controller"]
    db = env["ctx"]["db"]

    goal_id = create_goal(client, headers, auto_advance=False)
    client.post(f"/api/goals/{goal_id}/plan", headers=headers)

    # simulate a crash: a run left RUNNING in the DB without a live process
    from app.ids import new_id, now_iso

    goal = db.query_one("SELECT * FROM goals WHERE id=?", (goal_id,))
    run_id = new_id("run")
    with db.write() as conn:
        conn.execute(
            """INSERT INTO runs(id, goal_id, task_id, decision_id, session_id, mode, status, is_auto, created_at)
               VALUES (?, ?, NULL, NULL, ?, ?, 'RUNNING', 0, ?)""",
            (run_id, goal_id, goal["worker_session_id"], goal["mode"], now_iso()),
        )
        conn.execute("UPDATE goals SET status='ACTIVE', stage='executing' WHERE id=?", (goal_id,))

    result = controller.recover_after_restart()
    assert run_id in result["recovered_runs"]

    row = db.query_one("SELECT * FROM runs WHERE id=?", (run_id,))
    assert row["status"] == "INTERRUPTED"
    assert row["error_class"] == "PROCESS_RESTART"
    g = db.query_one("SELECT * FROM goals WHERE id=?", (goal_id,))
    assert g["status"] == "PAUSED" and g["stage"] == "recovered"

    types = [e["type"] for e in db.query("SELECT type FROM events WHERE run_id=?", (run_id,))]
    assert "run.recovered" in types
    # no automatic re-dispatch: still exactly one run for this goal
    n = db.query("SELECT COUNT(*) c FROM runs WHERE goal_id=?", (goal_id,))[0]["c"]
    assert n == 1
