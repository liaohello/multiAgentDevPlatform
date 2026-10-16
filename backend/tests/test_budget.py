"""Budget: ledger semantics, 100% stop lock, persistence across restart, resume."""
from conftest import create_goal


def test_usage_dedupe_and_reset_semantics(env):
    ctx = env["ctx"]
    budget = ctx["budget"]
    db = ctx["db"]

    # dedupe: the same cumulative snapshot recorded once
    first = budget.thread_snapshot_to_delta(
        thread_id="t-1", cumulative_total=1000, run_id=None, goal_id=None, session_id=None,
        provider="openai", model="m",
    )
    assert first is not None and first["total_tokens"] == 1000
    second = budget.thread_snapshot_to_delta(
        thread_id="t-1", cumulative_total=1000, run_id=None, goal_id=None, session_id=None,
        provider="openai", model="m",
    )
    assert second is None  # duplicate snapshot produces no new row
    rows = db.query("SELECT COUNT(*) c FROM usage_events WHERE dedupe_key='thread:t-1:total:1000'")
    assert rows[0]["c"] == 1

    # increment: 1500 -> +500
    third = budget.thread_snapshot_to_delta(
        thread_id="t-1", cumulative_total=1500, run_id=None, goal_id=None, session_id=None,
        provider="openai", model="m",
    )
    assert third["total_tokens"] == 500

    # reset observed: lower cumulative -> recorded as unknown, not zero-deducted
    reset = budget.thread_snapshot_to_delta(
        thread_id="t-1", cumulative_total=200, run_id=None, goal_id=None, session_id=None,
        provider="openai", model="m",
    )
    assert reset is None
    ev = db.query("SELECT * FROM events WHERE type='budget.usage_reset_observed'")
    assert len(ev) == 1
    unknown = db.query("SELECT * FROM usage_events WHERE exactness='unknown'")
    assert len(unknown) == 1


def test_budget_100_percent_blocks_next_round_and_persists_across_restart(env, tmp_path):
    from conftest import make_settings
    from app.main import build_app
    from fastapi.testclient import TestClient

    client, headers = env["client"], env["headers"]
    # budget = 5000: plan 1800 + run1 3500 = 5300 >= 5000 -> gate closes
    goal_id = create_goal(
        client, headers, scenario="budget", budget_tokens=5000, auto_advance=True,
    )
    client.post(f"/api/goals/{goal_id}/plan", headers=headers)
    client.post(f"/api/goals/{goal_id}/start", headers=headers)

    bundle = client.get(f"/api/goals/{goal_id}", headers=headers).json()
    usage = bundle["usage"]
    assert usage["gate"] == "CLOSED", usage
    assert usage["committed_tokens"] >= 5000
    assert bundle["goal"]["status"] == "PAUSED"
    assert bundle["goal"]["stage"] == "budget_blocked"

    # next round blocked, with a clear reason (409)
    r = client.post(f"/api/goals/{goal_id}/start", headers=headers)
    assert r.status_code == 409

    # events: closed + review admission rejection recorded
    types = [e["type"] for e in bundle["events"]]
    assert "budget.closed" in types
    closed_events = [e for e in bundle["events"] if e["type"] == "budget.closed"]
    assert any(e["payload"].get("cause") == "review_admission" for e in closed_events)

    # resume requires budget.resume (goal resume alone is refused)
    r = client.post(f"/api/goals/{goal_id}/resume", json={"note": "try resume"}, headers=headers)
    assert r.status_code == 409

    # restart: new app on the same data dir; lock must persist
    st = env["settings"]
    st.pinned_token = "restart-token"
    app2 = build_app(st)
    client2 = TestClient(app2)
    client2.__enter__()
    try:
        headers2 = {"X-AgentProj-Token": "restart-token"}
        usage2 = client2.get(f"/api/goals/{goal_id}/usage", headers=headers2).json()
        assert usage2["summary"]["gate"] == "CLOSED"  # restart did not clear the lock
        r = client2.post(f"/api/goals/{goal_id}/start", headers=headers2)
        assert r.status_code == 409

        # explicit user resume with a budget adjustment
        r = client2.post(
            f"/api/goals/{goal_id}/budget/resume",
            json={"note": "用户批准：补充预算并恢复", "budget_tokens": 20000},
            headers=headers2,
        )
        assert r.status_code == 200, r.text
        assert r.json()["usage"]["gate"] == "OPEN"

        # goal resume now works; review proceeds; fix; run2 passes; complete
        r = client2.post(f"/api/goals/{goal_id}/resume", json={"note": "继续"}, headers=headers2)
        assert r.status_code == 200, r.text
        r = client2.post(f"/api/goals/{goal_id}/review", headers=headers2)
        assert r.status_code == 200, r.text
        bundle2 = client2.get(f"/api/goals/{goal_id}", headers=headers2).json()
        assert bundle2["goal"]["status"] == "COMPLETED", bundle2["goal"]
        assert bundle2["usage"]["gate"] == "OPEN"

        # resume event recorded with the note
        resumed = [e for e in bundle2["events"] if e["type"] == "budget.resumed"]
        assert resumed and resumed[-1]["payload"]["note"].startswith("用户批准")
    finally:
        client2.__exit__(None, None, None)
