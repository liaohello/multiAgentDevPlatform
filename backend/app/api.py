"""HTTP API. Auth (loopback + token + origin) is enforced in main.py middleware.

Command endpoints accept an `Idempotency-Key` header; repeated calls return the
stored receipt and never start extra work.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .adapters.wsl import WslTransport
from .budget import BudgetBlocked
from .controller import ConflictError
from .events import list_events

router = APIRouter(prefix="/api")


def get_ctx(request: Request):
    return request.app.state.ctx


# ------------------------------------------------------------------ models
class WorkspaceCreate(BaseModel):
    name: str
    windows_path: str
    fs_side: str = "windows"


class GoalCreate(BaseModel):
    title: str
    request: str
    mode: str = "simulation"  # real | simulation
    workspace_mode: str = "demo"  # demo | existing
    workspace_id: str | None = None
    budget_tokens: int | None = None
    scenario: str = "demo"
    auto_advance: bool = True
    sol_model: str | None = None
    sol_effort: str | None = None
    worker_model: str | None = None


class SkillSelection(BaseModel):
    skill_ids: list[str] = Field(default_factory=list)


class SkillAllowed(BaseModel):
    allowed: bool


class WikiImport(BaseModel):
    workspace_id: str
    source_path: str
    session_id: str | None = None
    goal_id: str | None = None
    note: str | None = None


class WikiScan(BaseModel):
    workspace_id: str
    subdir: str = "."


class WikiPathRead(BaseModel):
    workspace_id: str
    rel_path: str


class BudgetResume(BaseModel):
    note: str
    budget_tokens: int | None = None


class OptimizeRequest(BaseModel):
    text: str


class NoteOnly(BaseModel):
    note: str = ""


# ------------------------------------------------------------------- meta
@router.get("/health")
def health(request: Request):
    ctx = get_ctx(request)
    return {
        "status": "ok",
        "version": ctx["version"],
        "data_dir": str(ctx["settings"].data_dir),
        "modes": ["real", "simulation"],
    }


@router.get("/env/adapters")
def env_adapters(request: Request):
    ctx = get_ctx(request)
    settings = ctx["settings"]
    windows = {"status": "PASS", "detail": f"codex bin: {settings.codex_bin}"}
    from pathlib import Path

    p = Path(settings.codex_bin)
    if p.is_absolute() and not p.is_file():
        windows = {"status": "BLOCKED", "detail": f"codex executable missing: {settings.codex_bin}"}
    transport = WslTransport(settings.wsl_distro, settings.wsl_codex_cmd)
    wsl = transport.probe()
    return {"windows_sol": windows, "wsl_worker": wsl, "wsl_distro": settings.wsl_distro}


@router.get("/models")
def models(request: Request):
    """Query the real runtime for models when possible; fallback list otherwise."""
    ctx = get_ctx(request)
    controller = ctx["controller"]
    try:
        from .adapters.codex_appserver import AppServerClient

        settings = ctx["settings"]
        client = AppServerClient(
            [settings.codex_bin, "app-server", "--listen", "stdio://"], label="models-probe"
        )
        try:
            client.start()
            result = client.request("model/list", {}, timeout=20)
        finally:
            client.close(kill=True)
        items = result.get("data") or result.get("models") or []
        out = []
        for m in items:
            efforts = [e.get("reasoningEffort") for e in (m.get("supportedReasoningEfforts") or [])]
            out.append({"id": m.get("id"), "display": m.get("displayName") or m.get("id"), "efforts": efforts})
        return {"source": "runtime", "models": out}
    except Exception as exc:  # noqa: BLE001
        return {
            "source": "fallback",
            "error": str(exc)[:300],
            "models": [
                {"id": "gpt-5.6-luna", "display": "GPT-5.6-Luna", "efforts": ["low", "medium", "high"]},
                {"id": "gpt-6-sol", "display": "GPT-6-Sol", "efforts": ["low", "medium", "high", "xhigh"]},
            ],
        }


# -------------------------------------------------------------- workspaces
@router.post("/workspaces")
def create_workspace(body: WorkspaceCreate, request: Request):
    ctx = get_ctx(request)
    try:
        return ctx["controller"].create_workspace(body.name, body.windows_path, fs_side=body.fs_side)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc))


@router.get("/workspaces")
def list_workspaces(request: Request):
    return get_ctx(request)["controller"].list_workspaces()


# ------------------------------------------------------------------ goals
@router.post("/goals")
def create_goal(body: GoalCreate, request: Request):
    ctx = get_ctx(request)
    try:
        return ctx["controller"].create_goal(
            workspace_mode=body.workspace_mode, workspace_id=body.workspace_id,
            title=body.title, request=body.request, mode=body.mode,
            budget_tokens=body.budget_tokens, scenario=body.scenario,
            auto_advance=body.auto_advance, sol_model=body.sol_model,
            sol_effort=body.sol_effort, worker_model=body.worker_model,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc))


@router.get("/goals")
def list_goals(request: Request, workspace_id: str | None = None):
    return get_ctx(request)["controller"].list_goals(workspace_id=workspace_id)


@router.get("/goals/{goal_id}")
def goal_bundle(goal_id: str, request: Request):
    try:
        return get_ctx(request)["controller"].get_goal_bundle(goal_id)
    except KeyError:
        raise HTTPException(404, "goal not found")


def _idem(ctx, key: str | None, endpoint: str):
    if not key:
        return None
    return ctx["controller"].command_receipt(f"{endpoint}:{key}")


def _store_idem(ctx, key: str | None, endpoint: str, response: dict):
    if key:
        ctx["controller"].store_receipt(f"{endpoint}:{key}", endpoint, "accepted", response)


@router.post("/goals/{goal_id}/plan")
def plan_goal(goal_id: str, request: Request, idempotency_key: str | None = Header(default=None)):
    ctx = get_ctx(request)
    cached = _idem(ctx, idempotency_key, f"plan:{goal_id}")
    if cached is not None:
        return {**cached, "duplicate": True}
    try:
        resp = ctx["controller"].plan_goal_async(goal_id)
    except (ConflictError, KeyError) as exc:
        raise HTTPException(409, str(exc))
    _store_idem(ctx, idempotency_key, f"plan:{goal_id}", resp)
    return resp


@router.post("/goals/{goal_id}/start")
def start_goal(goal_id: str, request: Request, idempotency_key: str | None = Header(default=None)):
    ctx = get_ctx(request)
    cached = _idem(ctx, idempotency_key, f"start:{goal_id}")
    if cached is not None:
        return {**cached, "duplicate": True}
    try:
        resp = ctx["controller"].start_run_async(goal_id, idempotency_key=idempotency_key)
    except ConflictError as exc:
        raise HTTPException(409, str(exc))
    except BudgetBlocked as exc:
        raise HTTPException(409, f"budget blocked: {exc.reason}")
    except KeyError:
        raise HTTPException(404, "goal not found")
    _store_idem(ctx, idempotency_key, f"start:{goal_id}", resp)
    return resp


@router.post("/goals/{goal_id}/review")
def review_goal(goal_id: str, request: Request, idempotency_key: str | None = Header(default=None)):
    ctx = get_ctx(request)
    cached = _idem(ctx, idempotency_key, f"review:{goal_id}")
    if cached is not None:
        return {**cached, "duplicate": True}
    try:
        resp = ctx["workflows"].trigger_goal_review(goal_id, idempotency_key=idempotency_key)
    except ConflictError as exc:
        raise HTTPException(409, str(exc))
    _store_idem(ctx, idempotency_key, f"review:{goal_id}", resp)
    return resp


@router.post("/goals/{goal_id}/pause")
def pause_goal(goal_id: str, body: NoteOnly, request: Request):
    try:
        return get_ctx(request)["controller"].pause_goal(goal_id, body.note)
    except KeyError:
        raise HTTPException(404, "goal not found")


@router.post("/goals/{goal_id}/resume")
def resume_goal(goal_id: str, body: NoteOnly, request: Request):
    try:
        return get_ctx(request)["controller"].resume_goal(goal_id, body.note)
    except (ConflictError, KeyError) as exc:
        raise HTTPException(409 if isinstance(exc, ConflictError) else 404, str(exc))


@router.post("/goals/{goal_id}/cancel")
def cancel_goal(goal_id: str, body: NoteOnly, request: Request):
    try:
        return get_ctx(request)["controller"].cancel_goal(goal_id, body.note)
    except KeyError:
        raise HTTPException(404, "goal not found")


@router.post("/goals/{goal_id}/budget/resume")
def resume_budget(goal_id: str, body: BudgetResume, request: Request):
    ctx = get_ctx(request)
    try:
        ctx["budget"].resume_gate(goal_id, note=body.note, budget_tokens=body.budget_tokens)
        return {"ok": True, "usage": ctx["budget"].usage_summary(goal_id)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc))


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str, body: NoteOnly, request: Request):
    try:
        return get_ctx(request)["controller"].cancel_run(run_id, body.note)
    except KeyError:
        raise HTTPException(404, "run not found")


@router.get("/goals/{goal_id}/usage")
def goal_usage(goal_id: str, request: Request):
    ctx = get_ctx(request)
    return {
        "summary": ctx["budget"].usage_summary(goal_id),
        "series": ctx["budget"].usage_series(goal_id),
    }


# ----------------------------------------------------------------- events
@router.get("/goals/{goal_id}/events")
def goal_events(goal_id: str, request: Request, after: int = 0, limit: int = 300):
    ctx = get_ctx(request)
    return {"events": list_events(ctx["db"], after_seq=after, limit=limit, goal_id=goal_id)}


@router.get("/stream")
async def stream(request: Request, cursor: int = Query(0), tseq: int = Query(0)):
    ctx = get_ctx(request)
    db = ctx["db"]
    bus = ctx["bus"]

    async def gen():
        last_cursor, last_t = cursor, tseq
        idle = 0
        while True:
            if await request.is_disconnected():
                break
            events = await asyncio.to_thread(list_events, db, after_seq=last_cursor, limit=200)
            transient = bus.read_transient(after_tseq=last_t)
            if events or transient:
                payload = {"events": events, "transient": transient}
                yield "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
                if events:
                    last_cursor = events[-1]["seq"]
                if transient:
                    last_t = transient[-1]["tseq"]
                idle = 0
            else:
                idle += 1
                if idle % 20 == 0:
                    yield ": keep-alive\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


# -------------------------------------------------------------- sessions
@router.get("/sessions")
def list_sessions(request: Request, workspace_id: str | None = None):
    return get_ctx(request)["controller"].list_sessions(workspace_id)


@router.get("/sessions/{session_id}/skills")
def session_skills(session_id: str, request: Request):
    return get_ctx(request)["skills"].session_skills(session_id)


@router.post("/sessions/{session_id}/skills")
def select_session_skills(session_id: str, body: SkillSelection, request: Request):
    ctx = get_ctx(request)
    try:
        return ctx["skills"].select_for_session(session_id, body.skill_ids)
    except (KeyError, PermissionError) as exc:
        raise HTTPException(400 if isinstance(exc, KeyError) else 403, str(exc))


# ----------------------------------------------------------------- skills
@router.get("/skills")
def list_skills(request: Request):
    return get_ctx(request)["skills"].list_registry()


class SkillImport(BaseModel):
    path: str
    skill_id: str | None = None


@router.post("/skills/import")
def import_skill(body: SkillImport, request: Request):
    ctx = get_ctx(request)
    try:
        return ctx["skills"].import_local(body.path, skill_id=body.skill_id)
    except FileNotFoundError:
        raise HTTPException(404, "skill file not found")


@router.post("/skills/{skill_id}/allowed")
def allow_skill(skill_id: str, body: SkillAllowed, request: Request):
    ctx = get_ctx(request)
    try:
        return ctx["skills"].set_allowed(skill_id, body.allowed)
    except KeyError:
        raise HTTPException(404, "skill not found")


@router.get("/runs/{run_id}/skills")
def run_skills(run_id: str, request: Request):
    return get_ctx(request)["skills"].usage_for_run(run_id)


# ---------------------------------------------------------------- evidence
@router.get("/evidence/{evidence_id}/content")
def evidence_content(evidence_id: str, request: Request, max_bytes: int = 200_000):
    ctx = get_ctx(request)
    row = ctx["db"].query_one("SELECT * FROM evidence WHERE id = ?", (evidence_id,))
    if not row:
        raise HTTPException(404, "evidence not found")
    path = ctx["settings"].resolve_stored_path(row["rel_path"])
    if not path.is_file():
        raise HTTPException(410, f"evidence file missing: {row['rel_path']}")
    raw = path.read_bytes()
    truncated = len(raw) > max_bytes
    text = raw[:max_bytes].decode("utf-8", errors="replace")
    return {
        "id": row["id"],
        "kind": row["kind"],
        "rel_path": row["rel_path"],
        "sha256": row["sha256"],
        "size": row["size"],
        "collected_at": row["collected_at"],
        "truncated": truncated,
        "content": text,
    }


# -------------------------------------------------------------- sessions
class SessionConfig(BaseModel):
    model: str | None = None
    reasoning_effort: str | None = None


@router.post("/sessions/{session_id}/config")
def update_session_config(session_id: str, body: SessionConfig, request: Request):
    """Change model/effort for subsequent turns; native thread (history) is kept."""
    ctx = get_ctx(request)
    controller = ctx["controller"]
    session = controller.get_session(session_id)
    if not session:
        raise HTTPException(404, "session not found")
    from .events import append_event as _append

    with ctx["db"].write() as conn:
        conn.execute(
            """UPDATE sessions SET model = COALESCE(?, model),
               reasoning_effort = COALESCE(?, reasoning_effort), updated_at = datetime('now')
               WHERE id = ?""",
            (body.model, body.reasoning_effort, session_id),
        )
        _append(
            ctx["db"], type_="session.updated",
            payload={
                "session_id": session_id,
                "previous": {"model": session["model"], "effort": session["reasoning_effort"]},
                "new": {"model": body.model or session["model"], "effort": body.reasoning_effort or session["reasoning_effort"]},
                "note": "applies to subsequent turns; native thread history preserved",
            },
            workspace_id=session["workspace_id"], session_id=session_id, conn=conn,
        )
    ctx["bus"].notify()
    return controller.get_session(session_id)


# ------------------------------------------------------------------- wiki
@router.get("/wiki")
def wiki_entries(request: Request, workspace_id: str):
    return get_ctx(request)["wiki"].list_entries(workspace_id)


@router.post("/wiki/import")
def wiki_import(body: WikiImport, request: Request):
    ctx = get_ctx(request)
    try:
        return ctx["wiki"].import_markdown(
            workspace_id=body.workspace_id, source_path=body.source_path,
            session_id=body.session_id, goal_id=body.goal_id, note=body.note,
        )
    except FileNotFoundError:
        raise HTTPException(404, "source file not found")


@router.post("/wiki/scan")
def wiki_scan(body: WikiScan, request: Request):
    ctx = get_ctx(request)
    try:
        return ctx["wiki"].scan_workspace_docs(body.workspace_id, body.subdir)
    except (KeyError, PermissionError) as exc:
        raise HTTPException(400 if isinstance(exc, KeyError) else 403, str(exc))


@router.get("/wiki/entries/{entry_id}/body")
def wiki_body(entry_id: str, request: Request, workspace_id: str | None = None):
    ctx = get_ctx(request)
    try:
        return ctx["wiki"].read_body(entry_id, requester_workspace_id=workspace_id)
    except KeyError:
        raise HTTPException(404, "entry not found")
    except (PermissionError, FileNotFoundError) as exc:
        raise HTTPException(403, str(exc))


@router.post("/wiki/read-path")
def wiki_read_path(body: WikiPathRead, request: Request):
    ctx = get_ctx(request)
    try:
        return ctx["wiki"].read_workspace_path(body.workspace_id, body.rel_path)
    except KeyError:
        raise HTTPException(404, "workspace not found")
    except (PermissionError, FileNotFoundError) as exc:
        raise HTTPException(403, str(exc))


# -------------------------------------------------------------- workflows
@router.post("/goals/{goal_id}/optimize")
def optimize(goal_id: str, body: OptimizeRequest, request: Request, idempotency_key: str | None = Header(default=None)):
    ctx = get_ctx(request)
    cached = _idem(ctx, idempotency_key, f"optimize:{goal_id}")
    if cached is not None:
        return {**cached, "duplicate": True}
    try:
        resp = ctx["workflows"].quick_optimize(goal_id, body.text)
    except BudgetBlocked as exc:
        raise HTTPException(409, f"budget blocked: {exc.reason}")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc))
    _store_idem(ctx, idempotency_key, f"optimize:{goal_id}", {"report_id": resp["report_id"]})
    return resp


@router.post("/goals/{goal_id}/postmortem")
def postmortem(goal_id: str, request: Request, idempotency_key: str | None = Header(default=None)):
    ctx = get_ctx(request)
    cached = _idem(ctx, idempotency_key, f"postmortem:{goal_id}")
    if cached is not None:
        return {**cached, "duplicate": True}
    try:
        resp = ctx["workflows"].postmortem(goal_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc))
    _store_idem(ctx, idempotency_key, f"postmortem:{goal_id}", {"report_id": resp["report_id"]})
    return resp


@router.post("/goals/{goal_id}/token-audit")
def token_audit(goal_id: str, request: Request, idempotency_key: str | None = Header(default=None)):
    ctx = get_ctx(request)
    cached = _idem(ctx, idempotency_key, f"token-audit:{goal_id}")
    if cached is not None:
        return {**cached, "duplicate": True}
    try:
        resp = ctx["workflows"].token_audit(goal_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc))
    _store_idem(ctx, idempotency_key, f"token-audit:{goal_id}", {"report_id": resp["report_id"]})
    return resp


@router.get("/workflows/reports")
def list_reports(request: Request, goal_id: str | None = None):
    return get_ctx(request)["workflows"].list_reports(goal_id)


@router.get("/workflows/reports/{report_id}")
def get_report(report_id: str, request: Request):
    report = get_ctx(request)["workflows"].get_report(report_id)
    if not report:
        raise HTTPException(404, "report not found")
    return report


# -------------------------------------------------------------- recovery
@router.post("/recovery/run")
def run_recovery(request: Request):
    return get_ctx(request)["controller"].recover_after_restart()
