"""Auth boundary, origin checks, and no-credential/reasoning persistence (A15)."""
import json


def test_auth_boundary(env):
    client = env["client"]
    # health is open
    assert client.get("/api/health").status_code == 200
    # everything else requires the token
    assert client.get("/api/goals").status_code == 401
    assert client.get("/api/goals", headers={"X-AgentProj-Token": "wrong"}).status_code == 401
    assert client.get("/api/goals", headers=env["headers"]).status_code == 200
    # foreign origin rejected
    r = client.get("/api/goals", headers={**env["headers"], "Origin": "https://evil.example"})
    assert r.status_code == 403
    # local origin accepted
    r = client.get("/api/goals", headers={**env["headers"], "Origin": "http://127.0.0.1:5173"})
    assert r.status_code == 200


def test_no_reasoning_or_credentials_in_persisted_data(env):
    from conftest import create_goal, run_simulation_goal

    client, headers = env["client"], env["headers"]
    goal_id = create_goal(client, headers)
    run_simulation_goal(client, headers, goal_id)

    db = env["ctx"]["db"]
    dump = []
    for table in ("events", "runs", "results", "reviews", "usage_events", "evidence", "goals", "sessions"):
        for row in db.query(f"SELECT * FROM {table}"):
            d = {k: v for k, v in dict(row).items() if k != "reasoning_effort"}
            dump.append(d)
    text = json.dumps(dump, ensure_ascii=False, default=str).lower()
    for forbidden in ("chain-of-thought", "api_key", "authorization:", "bearer ", "sk-", '"reasoning"', "reasoning_content"):
        assert forbidden not in text, f"forbidden content persisted: {forbidden}"

    # reasoning events are dropped by the adapter's allowed-list
    events = db.query("SELECT type FROM events")
    assert all("reasoning" not in e["type"] for e in events)
