"""Skills (A12) and Wiki (A13) behavior."""
from conftest import create_goal, run_simulation_goal


def test_skills_config_vs_invocation(env):
    client, headers = env["client"], env["headers"]

    # built-in registry seeded; all allowed by default
    skills = client.get("/api/skills", headers=headers).json()
    ids = {s["id"] for s in skills}
    assert {"prompt-optimizer", "goal-review", "goal-collaboration-postmortem", "token-audit"} <= ids

    # two sessions, different selections -> different visible sets
    goal_id = create_goal(client, headers, auto_advance=False)
    bundle = client.get(f"/api/goals/{goal_id}", headers=headers).json()
    sol_sid = bundle["goal"]["sol_session_id"]
    worker_sid = bundle["goal"]["worker_session_id"]

    r = client.post(f"/api/sessions/{sol_sid}/skills", json={"skill_ids": ["goal-review"]}, headers=headers)
    assert r.status_code == 200
    r = client.post(
        f"/api/sessions/{worker_sid}/skills",
        json={"skill_ids": ["prompt-optimizer", "token-audit"]}, headers=headers,
    )
    assert r.status_code == 200
    sol_skills = {s["skill_id"] for s in client.get(f"/api/sessions/{sol_sid}/skills", headers=headers).json()}
    worker_skills = {s["skill_id"] for s in client.get(f"/api/sessions/{worker_sid}/skills", headers=headers).json()}
    assert sol_skills == {"goal-review"}
    assert worker_skills == {"prompt-optimizer", "token-audit"}

    # selection alone must NOT be recorded as invocation: run and check states
    client.post(f"/api/goals/{goal_id}/plan", headers=headers)
    client.post(f"/api/goals/{goal_id}/start", headers=headers)
    bundle = client.get(f"/api/goals/{goal_id}", headers=headers).json()
    run = bundle["runs"][0]
    usage = client.get(f"/api/runs/{run['id']}/skills", headers=headers).json()
    states: dict[str, set[str]] = {}
    for u in usage:
        states.setdefault(u["skill_id"], set()).add(u["state"])
    assert states.get("prompt-optimizer") == {"configured", "provided"}
    assert states.get("token-audit") == {"configured", "provided"}
    assert not any("invoked_observed" in s or "loaded_observed" in s for s in states.values())

    # disallowed skill cannot be selected
    client.post("/api/skills/token-audit/allowed", json={"allowed": False}, headers=headers)
    r = client.post(f"/api/sessions/{worker_sid}/skills", json={"skill_ids": ["token-audit"]}, headers=headers)
    assert r.status_code == 403


def test_wiki_import_scope_and_denials(env, tmp_path):
    client, headers = env["client"], env["headers"]

    goal_id = create_goal(client, headers, auto_advance=False)
    bundle = client.get(f"/api/goals/{goal_id}", headers=headers).json()
    ws_id = bundle["goal"]["workspace_id"]
    ws_path = bundle["workspace"]["windows_path"]

    # explicit markdown import: hash + scope recorded
    src = tmp_path / "notes.md"
    src.write_text("# 需求笔记\n\nnormalize_tags 的行为约定。\n", encoding="utf-8")
    r = client.post(
        "/api/wiki/import",
        json={"workspace_id": ws_id, "source_path": str(src), "note": "A13 evidence"},
        headers=headers,
    )
    assert r.status_code == 200
    entry = r.json()
    assert entry["imported"] == 1 and entry["content_hash"].startswith("sha256:")
    assert entry["scope"] == "workspace"

    # body read within the workspace is fine
    r = client.get(f"/api/wiki/entries/{entry['id']}/body", params={"workspace_id": ws_id}, headers=headers)
    assert r.status_code == 200 and "normalize_tags" in r.json()["body"]

    # cross-workspace read without authorization is denied BEFORE reading content
    other_ws = client.post(
        "/api/workspaces", json={"name": "other", "windows_path": str(tmp_path)}, headers=headers
    ).json()
    r = client.get(f"/api/wiki/entries/{entry['id']}/body", params={"workspace_id": other_ws["id"]}, headers=headers)
    assert r.status_code == 403
    denied = env["ctx"]["db"].query("SELECT * FROM events WHERE type='wiki.denied'")
    assert denied, "wiki.denied event missing"

    # path escaping the workspace root is denied
    r = client.post(
        "/api/wiki/read-path",
        json={"workspace_id": ws_id, "rel_path": "../../../etc/passwd"},
        headers=headers,
    )
    assert r.status_code == 403
    denied = env["ctx"]["db"].query("SELECT * FROM events WHERE type='wiki.denied'")
    assert len(denied) >= 2

    # scan lists markdown metadata inside the workspace only
    r = client.post("/api/wiki/scan", json={"workspace_id": ws_id, "subdir": "."}, headers=headers)
    assert r.status_code == 200
    entries = client.get("/api/wiki", params={"workspace_id": ws_id}, headers=headers).json()
    assert any(e["title"] == "Demo 任务工作目录" for e in entries)
