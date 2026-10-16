"""FastAPI application factory.

Local security model (design §20):
- binds to 127.0.0.1 only;
- every /api request (except /api/health) requires the per-start session token;
- Origin headers, when present, must be a known local origin;
- the served index.html carries the token for the browser; a foreign page
  cannot read it (CORS + token), so "localhost" alone does not authorize a page.
"""
from __future__ import annotations

import json
import secrets
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from . import __version__
from .api import router
from .budget import Budget
from .config import Settings, settings
from .controller import Controller
from .db import Database
from .events import EventBus
from .evidence import EvidenceCollector
from .skills import SkillManager
from .wiki import WikiManager
from .workflows import Workflows

TOKEN_PLACEHOLDER = "__AGENTPROJ_TOKEN__"


def build_app(custom_settings: Settings | None = None) -> FastAPI:
    st = custom_settings or settings
    st.ensure_dirs()
    st.token = st.pinned_token or secrets.token_urlsafe(24)

    db = Database(st.db_path)
    bus = EventBus()
    budget = Budget(db, bus)
    evidence = EvidenceCollector(db, bus, st)
    controller = Controller(db, bus, budget, evidence, st)
    skills = SkillManager(db, bus, st)
    wiki = WikiManager(db, bus, st)
    workflows = Workflows(db, bus, controller, budget, st)
    controller.skills = skills

    skills.seed_builtins()

    import contextlib
    from datetime import datetime as _dt

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        # Recovery first: in-flight runs become INTERRUPTED (never auto-redispatched);
        # budget locks stay exactly as they were before the restart.
        recovered = controller.recover_after_restart()
        runtime_file = st.data_dir / "runtime.json"
        import os as _os

        runtime_file.write_text(
            json.dumps(
                {
                    "port": st.port,
                    "token": st.token,
                    "pid": _os.getpid(),
                    "started_at": _dt.now().isoformat(timespec="seconds"),
                    "recovered_runs": recovered.get("recovered_runs", []),
                },
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
        print(f"[agentProj] 工作台已启动: http://127.0.0.1:{st.port}")
        print(f"[agentProj] 会话令牌保存在: {runtime_file}")
        yield

    app = FastAPI(title="agentProj workbench", version=__version__, lifespan=lifespan)
    app.state.ctx = {
        "settings": st,
        "db": db,
        "bus": bus,
        "budget": budget,
        "evidence": evidence,
        "controller": controller,
        "skills": skills,
        "wiki": wiki,
        "workflows": workflows,
        "version": __version__,
    }

    allowed_origins = [
        f"http://127.0.0.1:{st.port}",
        f"http://localhost:{st.port}",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/") and path != "/api/health":
            origin = request.headers.get("origin")
            if origin and origin not in allowed_origins:
                return JSONResponse({"detail": "origin not allowed"}, status_code=403)
            token = request.headers.get("x-agentproj-token") or request.query_params.get("token")
            if token != st.token:
                return JSONResponse({"detail": "invalid or missing session token"}, status_code=401)
        return await call_next(request)

    app.include_router(router)

    # ---- static UI (built) -------------------------------------------------
    dist = st.ui_dist
    index_path = dist / "index.html"

    @app.get("/")
    def index():
        if index_path.is_file():
            html = index_path.read_text(encoding="utf-8").replace(TOKEN_PLACEHOLDER, st.token or "")
            return PlainTextResponse(html, media_type="text/html; charset=utf-8")
        return PlainTextResponse(
            "UI 尚未构建。请先运行 `npm run build`（见 README），或使用开发模式（Vite 5173）。",
            status_code=200,
        )

    if dist.is_dir():
        from fastapi.staticfiles import StaticFiles

        app.mount("/assets", StaticFiles(directory=str(dist / "assets")), name="assets")

        @app.get("/favicon.ico")
        def favicon():
            f = dist / "favicon.ico"
            if f.is_file():
                return FileResponse(f)
            return PlainTextResponse("", status_code=204)

    return app


app = build_app()
