"""End-to-end deterministic simulation: fail -> replan -> fix -> review -> complete."""
from conftest import create_goal, run_simulation_goal


def test_full_simulation_loop_with_failure_replan_fix(env):
    client, headers = env["client"], env["headers"]
    goal_id = create_goal(client, headers)
    bundle = run_simulation_goal(client, headers, goal_id)

    goal = bundle["goal"]
    assert goal["mode"] == "simulation"
    assert goal["status"] == "COMPLETED", bundle["goal"]

    # plan v1 frozen, then revised to v2 after the failed review
    assert goal["plan_version"] == 2
    assert [p["version"] for p in bundle["plans"]] == [1, 2]

    runs = bundle["runs"]
    assert len(runs) == 2, [r["status"] for r in runs]
    assert runs[0]["status"] == "SUCCEEDED"
    assert runs[0]["result"]["status"] == "failed"  # tests failed, honestly reported
    assert runs[1]["status"] == "SUCCEEDED"
    assert runs[1]["result"]["status"] == "completed"

    # evidence belongs to its run and is on disk
    for run in runs:
        assert run["evidence"], f"run {run['id']} has no evidence"
        for ev in run["evidence"]:
            assert (env["settings"].project_root / ev["rel_path"]).is_file()

    # review chain: FAIL -> replan; PASS -> completed (applied by Python)
    reviews = bundle["reviews"]
    assert len(reviews) == 2
    assert reviews[0]["overall"] == "FAIL"
    assert reviews[0]["applied"] == 1 and reviews[0]["applied_action"] == "replan"
    assert reviews[1]["overall"] == "PASS"
    assert reviews[1]["applied"] == 1 and reviews[1]["applied_action"] == "completed"

    # causal chain: every run has a decision; review cites the prior result
    assert all(r["decision_id"] for r in runs)
    assert reviews[0]["run_id"] == runs[0]["id"]
    assert reviews[1]["run_id"] == runs[1]["id"]

    # acceptance verdicts cite evidence ids that exist in this run
    ev_ids_run2 = {e["id"] for e in runs[1]["evidence"]}
    for v in reviews[1]["verdicts"]:
        if v["status"] == "PASS":
            assert v["evidence_ids"], f"PASS verdict without evidence: {v}"
            assert set(v["evidence_ids"]) <= ev_ids_run2

    # completion event present
    types = [e["type"] for e in bundle["events"]]
    for expected in ("goal.planned", "run.queued", "run.completed", "review.created", "review.applied", "goal.completed"):
        assert expected in types, f"missing event {expected}"


def test_run_fail_does_not_complete_goal_without_review(env):
    """No review => no completion, even if tests would pass."""
    client, headers = env["client"], env["headers"]
    goal_id = create_goal(client, headers, auto_advance=False)
    client.post(f"/api/goals/{goal_id}/plan", headers=headers)
    client.post(f"/api/goals/{goal_id}/start", headers=headers)
    bundle = client.get(f"/api/goals/{goal_id}", headers=headers).json()
    assert bundle["goal"]["status"] == "ACTIVE"  # run done, waiting for review
    assert len(bundle["reviews"]) == 0
