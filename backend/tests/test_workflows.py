"""Four lightweight workflows (A14): optimizer, review, postmortem, token audit."""
from conftest import create_goal, run_simulation_goal


def test_workflows_reference_existing_facts(env):
    client, headers = env["client"], env["headers"]
    goal_id = create_goal(client, headers)
    run_simulation_goal(client, headers, goal_id)

    # 1) Quick Prompt Optimizer: shows original vs optimized + differences
    r = client.post(
        f"/api/goals/{goal_id}/optimize",
        json={"text": "帮我写个 normalize_tags，要去空格去重"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    opt = r.json()
    assert opt["mode"] == "simulation"
    assert opt["report"]["optimized"] and opt["report"]["differences"]
    assert "优化后的 Prompt" in opt["markdown"]

    # 2) Goal Review is already in the loop — verify the demo goal's reviews exist
    bundle = client.get(f"/api/goals/{goal_id}", headers=headers).json()
    assert len(bundle["reviews"]) >= 2

    # 3) Postmortem: causal chain + efficiency metrics from real records
    r = client.post(f"/api/goals/{goal_id}/postmortem", headers=headers)
    assert r.status_code == 200, r.text
    pm = r.json()
    assert pm["mode"] == "simulation"
    trace = pm["report"]["decision_trace"]
    assert len(trace) == 2  # two runs, each with decision + review
    assert all(node["decision"] and node["run"] for node in trace)
    eff = pm["report"]["efficiency"]
    assert eff["total_runs"] == 2 and eff["rework_rounds"] == 1
    assert eff["milestones_reached"] == 1 and eff["tokens_per_milestone"] > 0
    assert "复盘" in pm["markdown"]

    # 4) Token Audit: facts from the usage ledger, budget boundary disclaimed
    r = client.post(f"/api/goals/{goal_id}/token-audit", headers=headers)
    assert r.status_code == 200, r.text
    ta = r.json()
    assert ta["report"]["findings"]
    assert "不负责计量" in ta["markdown"]

    # reports are listed and retrievable
    reports = client.get("/api/workflows/reports", params={"goal_id": goal_id}, headers=headers).json()
    assert {x["kind"] for x in reports} >= {"prompt-optimizer-quick", "goal-collaboration-postmortem", "token-audit"}
    detail = client.get(f"/api/workflows/reports/{ta['report_id']}", headers=headers).json()
    assert detail["kind"] == "token-audit"
