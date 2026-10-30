# -*- coding: utf-8 -*-
"""워시케어 서비스 진입점.

  docker compose up -d db && alembic upgrade head
  uvicorn backend.main:app --reload --port 8000
"""
import secrets

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware

from . import auth
from .api import conversations, products
from .db import engine
from .settings import settings


def create_app():
    app = FastAPI(title="워시케어", docs_url=None, redoc_url=None, openapi_url=None)
    # Starlette 세션은 Google 로그인의 state·nonce를 10분 동안 담는 데만 씁니다. 로그인 세션은 DB(wc_session)에 있습니다.
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret or secrets.token_urlsafe(32),
                       session_cookie="wc_oauth", max_age=600, same_site="lax", https_only=settings.cookie_secure)
    app.include_router(auth.router)
    app.include_router(products.router)
    app.include_router(conversations.router)

    @app.get("/healthz")
    def healthz():
        try:
            with engine.connect() as conn:
                conn.execute(text("select 1"))
        except Exception:
            return JSONResponse({"ok": False, "db": False}, status_code=503)
        return {"ok": True, "db": True}

    return app


app = create_app()
