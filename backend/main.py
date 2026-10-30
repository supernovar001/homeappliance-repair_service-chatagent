# -*- coding: utf-8 -*-
"""워시케어 서비스 진입점.

  docker compose up -d db && alembic upgrade head
  uvicorn backend.main:app --port 8000

시작할 때 app.py(검색·재정렬 모델)를 불러오므로 서버가 열리기까지 수십 초 걸립니다.
기존 Gradio 화면은 /demo에 그대로 둡니다.
"""
import asyncio
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware

from . import auth, retention
from .api import admin, bookmarks, consult, conversations, memories, products
from .db import engine as db_engine
from .jobs import JobRunner
from .settings import ROOT_DIR, settings

DIST_DIR = ROOT_DIR / "frontend" / "dist"


def create_app(engine=None, background=True):
    """engine을 넘기지 않으면 실제 AI(app.py)를 불러옵니다. 테스트는 FakeEngine을 넘기고 보관 기간 작업을 끕니다."""
    if engine is None:
        from .engine import WasherEngine
        engine = WasherEngine().load()

    @asynccontextmanager
    async def lifespan(app):
        app.state.jobs.recover()
        task = asyncio.create_task(retention.run_forever()) if background else None
        yield
        if task:
            task.cancel()
        app.state.jobs.shutdown()

    app = FastAPI(title="워시케어", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.engine = engine
    app.state.jobs = JobRunner(engine, settings.max_concurrent_consults, settings.job_timeout_seconds)
    # Starlette 세션은 Google 로그인의 state·nonce를 10분 동안 담는 데만 씁니다. 로그인 세션은 DB(wc_session)에 있습니다.
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret or secrets.token_urlsafe(32),
                       session_cookie="wc_oauth", max_age=600, same_site="lax", https_only=settings.cookie_secure)
    app.include_router(auth.router)
    app.include_router(products.router)
    app.include_router(conversations.router)
    app.include_router(consult.router)
    app.include_router(memories.router)
    app.include_router(bookmarks.router)
    app.include_router(admin.router)

    @app.get("/healthz")
    def healthz():
        try:
            with db_engine.connect() as conn:
                conn.execute(text("select 1"))
            db_ok = True
        except Exception:
            db_ok = False
        ok = db_ok and engine.ready
        return JSONResponse({"ok": ok, "db": db_ok, "ai": engine.ready}, status_code=200 if ok else 503)

    if engine.demo is not None:
        import gradio as gr
        app = gr.mount_gradio_app(app, engine.demo, path="/demo", auth=engine.demo_auth, theme=gr.themes.Soft())
    mount_frontend(app)
    return app


def mount_frontend(app):
    """빌드한 Vue 화면(frontend/dist)을 제공합니다. 화면 경로(/consult/… 등)는 모두 index.html로 보냅니다."""
    if not (DIST_DIR / "index.html").exists():
        return
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith(("api/", "auth/", "demo")):
            raise HTTPException(404)
        file = (DIST_DIR / path).resolve()
        if path and file.is_file() and DIST_DIR.resolve() in file.parents:
            return FileResponse(file)
        return FileResponse(DIST_DIR / "index.html", headers={"Cache-Control": "no-cache"})


def _app():
    # 테스트에서 backend.main을 불러와도 AI를 읽지 않도록, uvicorn이 이 속성을 찾을 때만 만듭니다.
    return create_app()


def __getattr__(name):
    if name == "app":
        globals()["app"] = _app()
        return globals()["app"]
    raise AttributeError(name)
