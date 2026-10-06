"""Web UI process: python -m uvicorn web.api.main:app --host 0.0.0.0 --port 8090"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from bot.config import ROOT, Settings, get_settings
from bot.db.connection import connect
from bot.deps import Deps
from bot.gpulock import GpuLock
from bot.llm.client import LLMClient

from .auth import COOKIE, Auth
from .routes import router

log = logging.getLogger(__name__)
STATIC = ROOT / "web" / "static"  # the built frontend (web/app -> npm run build)


def build_deps(s: Settings) -> Deps:
    conn = connect(s.db_path, s.migrations_dir, s.embed_dim)
    llm = LLMClient(s.llm_url, routine=s.routine_model_name, answer=s.answer_model_name, embed=s.embed_model_name,
                    timeout=s.llm_timeout, json_schema_enabled=s.llm_json_schema)
    return Deps(settings=s, conn=conn, llm=llm, gpu_lock=GpuLock(s.data_dir / "gpu.lock"))


class Login(BaseModel):
    password: str


def create_app(deps: Deps | None = None, static_dir: Path = STATIC) -> FastAPI:
    def make_auth(s: Settings) -> Auth:
        return Auth(s.web_password, s.data_dir / "web_secret", s.web_session_days)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app.state.deps is None:  # production: build everything here, not at import time
            s = get_settings()
            logging.basicConfig(level=s.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
            if not s.web_password:
                log.error("WEB_PASSWORD is empty: nobody can log in. Set it in .env")
            app.state.deps = build_deps(s)
            app.state.auth = make_auth(s)
        yield
        await app.state.deps.llm.close()

    app = FastAPI(title="WhaleVault", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.deps = deps
    if deps is not None:  # tests inject deps and may not run the lifespan
        app.state.auth = make_auth(deps.settings)

    def require_login(request: Request) -> None:
        request.app.state.auth.require(request)

    @app.post("/api/login")
    async def login(body: Login, request: Request, response: Response) -> dict:
        auth: Auth = request.app.state.auth
        if not await auth.check_password(body.password):
            raise HTTPException(401, "wrong password")
        response.set_cookie(COOKIE, auth.issue(), max_age=auth.days * 86400, httponly=True, samesite="lax")
        return {"ok": True}

    @app.post("/api/logout")
    async def logout(response: Response) -> dict:
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @app.get("/api/me", dependencies=[Depends(require_login)])
    async def me() -> dict:
        return {"ok": True}

    app.include_router(router, dependencies=[Depends(require_login)])

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        """Built frontend; unknown paths get index.html (client-side routing). The SPA itself shows
        the login page when the API answers 401."""
        if path.startswith("api/"):
            raise HTTPException(404)
        f = (static_dir / path).resolve()
        if path and f.is_file() and static_dir.resolve() in f.parents:
            cache = "public, max-age=31536000, immutable" if "/_app/immutable/" in f"/{path}" else "no-cache"
            return FileResponse(f, headers={"Cache-Control": cache})
        index = static_dir / "index.html"
        if not index.exists():
            return Response("Frontend is not built: cd web/app && npm ci && npm run build", media_type="text/plain")
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
