# -*- coding: utf-8 -*-
"""Google 로그인(OIDC)과 서버 세션.

- Authlib이 state·nonce와 ID 토큰의 서명·iss·aud·만료를 검사합니다. email_verified가 아니면 로그인하지 않습니다.
- 세션 쿠키(wc_session)에는 무작위 토큰만 담고, DB에는 그 sha256만 저장합니다.
- 상태를 바꾸는 요청은 세션별 CSRF 토큰(X-CSRF-Token)과 Origin을 확인합니다.
- 관리자 여부는 요청마다 ADMIN_EMAILS와 비교합니다(DB에 저장하지 않음).
"""
import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from . import models
from .db import get_db, utcnow
from .settings import settings

COOKIE_NAME = "wc_session"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

router = APIRouter()


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db, user):
    """새 세션을 만들고 쿠키에 넣을 토큰 원문을 돌려줍니다."""
    token = secrets.token_urlsafe(32)
    db.add(models.Session(user_id=user.id, token_hash=hash_token(token), csrf_token=secrets.token_urlsafe(32),
                          expires_at=utcnow() + timedelta(days=settings.session_days)))
    return token


def is_admin(user):
    return user.email.lower() in settings.admin_emails


@dataclass
class Viewer:
    user: models.User
    session: models.Session

    @property
    def is_admin(self):
        return is_admin(self.user)


def current_viewer(request: Request, db: DbSession = Depends(get_db)) -> Viewer:
    token = request.cookies.get(COOKIE_NAME)
    row = db.execute(
        select(models.Session, models.User).join(models.User, models.User.id == models.Session.user_id)
        .where(models.Session.token_hash == hash_token(token), models.Session.expires_at > utcnow())
    ).first() if token else None
    if row is None:
        raise HTTPException(401, "로그인이 필요합니다.")
    session, user = row
    if request.method not in SAFE_METHODS:
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") not in settings.allowed_origins:
            raise HTTPException(403, "허용되지 않은 출처의 요청입니다.")
        if not secrets.compare_digest(request.headers.get("x-csrf-token", ""), session.csrf_token):
            raise HTTPException(403, "CSRF 토큰이 맞지 않습니다.")
    return Viewer(user=user, session=session)


def admin_viewer(viewer: Viewer = Depends(current_viewer)) -> Viewer:
    if not viewer.is_admin:
        raise HTTPException(403, "관리자만 볼 수 있습니다.")
    return viewer


@router.get("/auth/google/login")
async def google_login(request: Request):
    if not settings.google_client_id:
        raise HTTPException(503, "Google 로그인이 설정되지 않았습니다(GOOGLE_CLIENT_ID).")
    return await oauth.google.authorize_redirect(request, f"{settings.base_url}/auth/google/callback")


@router.get("/auth/google/callback")
async def google_callback(request: Request, db: DbSession = Depends(get_db)):
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError:
        return RedirectResponse("/?login_error=oauth", status_code=303)
    info = token.get("userinfo") or {}
    if not info.get("email_verified") or not info.get("email") or not info.get("sub"):
        return RedirectResponse("/?login_error=unverified", status_code=303)
    user = db.scalar(select(models.User).where(models.User.google_sub == info["sub"]))
    if user is None:
        user = models.User(google_sub=info["sub"], email=info["email"].lower())
        db.add(user)
    user.email, user.name, user.picture, user.last_login_at = info["email"].lower(), info.get("name", ""), info.get("picture", ""), utcnow()
    db.flush()
    session_token = create_session(db, user)
    db.commit()
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(COOKIE_NAME, session_token, max_age=settings.session_days * 86400, httponly=True,
                        secure=settings.cookie_secure, samesite="lax", path="/")
    return response


@router.post("/auth/logout", status_code=204)
def logout(viewer: Viewer = Depends(current_viewer), db: DbSession = Depends(get_db)):
    db.execute(delete(models.Session).where(models.Session.id == viewer.session.id))
    db.commit()
    response = Response(status_code=204)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response
