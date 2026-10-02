"""Fábrica da aplicação web (FastAPI): API + WebSocket + interface."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import intel_routes, routes, voice_routes, ws
from .config import Settings
from .container import Sexta, build_sexta
from .llm.base import LLMProvider

WEB_DIR = Path(__file__).parent / "web"
log = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    provider: LLMProvider | None = None,
    sexta: Sexta | None = None,
) -> FastAPI:
    sexta = sexta or build_sexta(settings, provider=provider)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if sexta.settings.background_services:
            loop = asyncio.get_running_loop()
            sexta.voice.start(loop)
            sexta.semantic.start()
            sexta.scheduler.start(loop)
        yield
        sexta.scheduler.stop()
        await asyncio.to_thread(sexta.browser.shutdown)
        await sexta.intel.http.aclose()
        running = [t for t in (sexta.tasks.task(i) for i in sexta.tasks.running_ids()) if t]
        sexta.tasks.cancel_all()
        if running:
            await asyncio.wait(running, timeout=5)
        sexta.close()

    app = FastAPI(title="Sexta-Feira", version=__version__, lifespan=lifespan, docs_url="/api/docs", redoc_url=None)
    app.state.sexta = sexta

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=sexta.settings.host_allowlist)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        host = request.headers.get("host", "127.0.0.1")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if not request.url.path.startswith("/api/docs"):
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; "
                f"connect-src 'self' ws://{host} wss://{host}; "
                "script-src 'self'; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com; "
                "img-src 'self' data:; media-src 'self' blob:; "
                "frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            )
        return response

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "name": "Sexta-Feira", "version": __version__}

    app.include_router(routes.router)
    app.include_router(voice_routes.router)
    app.include_router(intel_routes.router)
    app.include_router(ws.router)

    @app.exception_handler(Exception)
    async def unhandled(_request: Request, exc: Exception):
        log.exception("Erro não tratado", exc_info=exc)
        return JSONResponse({"detail": "Erro interno. Veja o log do servidor."}, status_code=500)

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    return app
