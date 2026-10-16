"""Shared test fixtures. Deterministic: sync mode + zero fake step delay."""
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

os.environ["AGENTPROJ_SYNC_MODE"] = "1"
os.environ.setdefault("AGENTPROJ_FAKE_STEP_DELAY", "0")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def make_settings(base: Path, *, token: str = "test-token"):
    from app.config import Settings

    st = Settings()
    st.data_dir = base / "data"
    st.db_path = st.data_dir / "state.sqlite"
    st.goals_dir = st.data_dir / "goals"
    st.imports_dir = st.data_dir / "imports"
    st.wiki_dir = st.data_dir / "wiki"
    st.skills_dir = st.data_dir / "skills"
    st.evidence_dir = st.data_dir / "evidence"
    st.demo_workspace = st.data_dir / "demo-workspace"
    st.pinned_token = token
    st.ensure_dirs()
    return st


@pytest.fixture
def env(tmp_path):
    """Fresh app + TestClient on isolated temp data dirs."""
    from app.main import build_app

    st = make_settings(tmp_path)
    application = build_app(st)
    client = TestClient(application)
    client.__enter__()
    yield {
        "app": application,
        "client": client,
        "ctx": application.state.ctx,
        "settings": st,
        "headers": {"X-AgentProj-Token": st.token},
    }
    client.__exit__(None, None, None)


@pytest.fixture
def controller(env):
    return env["ctx"]["controller"]


def create_goal(client, headers, **overrides):
    body = {
        "title": "实现 normalize_tags",
        "request": "实现 normalize_tags(text)：按逗号拆分、去首尾空白、忽略空项、去重并保留顺序。",
        "mode": "simulation",
        "workspace_mode": "demo",
        "scenario": "demo",
        "auto_advance": True,
    }
    body.update(overrides)
    resp = client.post("/api/goals", json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["goal"]["id"]


def run_simulation_goal(client, headers, goal_id):
    """plan -> start (sync mode runs the whole auto loop to completion)."""
    r = client.post(f"/api/goals/{goal_id}/plan", headers=headers)
    assert r.status_code == 200, r.text
    r = client.post(f"/api/goals/{goal_id}/start", headers=headers)
    assert r.status_code == 200, r.text
    return client.get(f"/api/goals/{goal_id}", headers=headers).json()
