"""Web UI process: python -m uvicorn web.api.main:app --host 0.0.0.0 --port 8090"""
import base64
import hashlib
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware

from bot import metrics
from bot.config import ROOT, Settings, get_settings
from bot.db.connection import connect
from bot.deps import Deps
from bot.gpulock import GpuLock
from bot.llm.client import LLMClient

from . import routes_dash, routes_misc, routes_notes, routes_settings, routes_topics
from .auth import COOKIE, Auth

log = logging.getLogger(__name__)
DIST = ROOT / "web" / "app" / "dist"  # the built frontend (web/app: npm run build)


def build_deps(s: Settings) -> Deps:
    conn = connect(s.db_path, s.migrations_dir, s.embed_dim)
    llm = LLMClient(s.llm_url, routine=s.routine_model_name, answer=s.answer_model_name, embed=s.embed_model_name,
                    timeout=s.llm_timeout, json_schema_enabled=s.llm_json_schema)
    llm.on_call = metrics.llm_hook(conn)
    return Deps(settings=s, conn=conn, llm=llm, gpu_lock=GpuLock(s.data_dir / "gpu.lock"))


def csp_for(index_html: str) -> str:
    """CSP without external sources. SvelteKit's SPA shell has one inline bootstrap script: allow it by hash."""
    hashes = " ".join(
        "'sha256-" + base64.b64encode(hashlib.sha256(m.encode()).digest()).decode() + "'"
        for m in re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", index_html, re.S) if m.strip())
    return ("default-src 'self'; script-src 'self' " + hashes + "; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; media-src 'self' blob:; font-src 'self'; connect-src 'self'; "
            "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")


class Login(BaseModel):
    password: str


def create_app(deps: Deps | None = None, dist: Path = DIST) -> FastAPI:
    def make_auth(s: Settings) -> Auth:
        return Auth(s.web_password, s.data_dir, s.web_session_days)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app.state.deps is None:  # production: build everything here, not at import time
            s = get_settings()
            logging.basicConfig(level=s.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
            app.state.deps = build_deps(s)
            app.state.auth = make_auth(s)
            if not app.state.auth.configured:
                log.error("WEB_PASSWORD is empty: nobody can log in. Set it in .env")
        yield
        await app.state.deps.llm.close()

    app = FastAPI(title="WhaleVault", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.deps = deps
    if deps is not None:  # tests inject deps and may not run the lifespan
        app.state.auth = make_auth(deps.settings)
    index = dist / "index.html"
    csp = csp_for(index.read_text(encoding="utf-8")) if index.exists() else "default-src 'self'"

    # ---- one error format: {"error": {"code", "message"}}
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        return JSONResponse({"error": {"code": exc.status_code, "message": str(exc.detail)}},
                            status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(x) for x in first.get("loc", [])[1:])
        return JSONResponse({"error": {"code": 400, "message": f"{where}: {first.get('msg', 'неверный запрос')}"}},
                            status_code=400)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = csp
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    # JS/CSS/JSON shrink 3-4x; Starlette leaves text/event-stream (the /ask stream) alone
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    def require_login(request: Request) -> None:
        request.app.state.auth.require(request)

    # ---- no session needed
    @app.get("/api/health")
    async def health(request: Request) -> dict:
        d = request.app.state.deps
        d.conn.execute("SELECT 1").fetchone()
        return {"status": "ok", "llm": await d.llm.running() is not None}

    @app.post("/api/auth/login")
    async def login(body: Login, request: Request, response: Response) -> dict:
        auth: Auth = request.app.state.auth
        if wait := auth.locked_for():
            raise HTTPException(429, f"Слишком много попыток. Подождите {wait} с")
        if not auth.check_password(body.password):
            raise HTTPException(401, "Неверный пароль")
        response.set_cookie(COOKIE, auth.issue(), max_age=auth.days * 86400, httponly=True, samesite="lax")
        return {"ok": True}

    @app.post("/api/auth/logout")
    async def logout(response: Response) -> dict:
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @app.get("/api/auth/me", dependencies=[Depends(require_login)])
    async def me() -> dict:
        return {"ok": True}

    for module in (routes_topics, routes_notes, routes_misc, routes_dash, routes_settings):
        app.include_router(module.router, dependencies=[Depends(require_login)])

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PATCH", "DELETE"], include_in_schema=False)
    async def api_404(path: str):
        raise HTTPException(404, "Нет такого адреса API")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        """Built frontend; other paths get index.html (client-side routing; the SPA shows login on 401)."""
        f = (dist / path).resolve()
        if path and f.is_file() and dist.resolve() in f.parents:
            cache = "public, max-age=31536000, immutable" if "/_app/immutable/" in f"/{path}" else "no-cache"
            return FileResponse(f, headers={"Cache-Control": cache})
        if not index.exists():
            return Response("Frontend is not built: cd web/app && npm ci && npm run build", media_type="text/plain")
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
