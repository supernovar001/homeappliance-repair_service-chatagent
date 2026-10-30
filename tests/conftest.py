# -*- coding: utf-8 -*-
"""백엔드 테스트 공통 설정.

  docker compose up -d db && pytest

로컬 Postgres의 washcare_test DB를 마이그레이션으로 새로 만듭니다. 로그인은 세션 행을 DB에 직접 넣어 처리합니다
(앱 코드에는 로그인 우회가 없습니다). OpenAI는 호출하지 않습니다.
"""
import os
import time
import uuid

import psycopg
import pytest

ADMIN_URL = os.getenv("TEST_ADMIN_DATABASE_URL", "postgresql://washcare:washcare@localhost:5433/washcare")
TEST_DB = "washcare_test"
os.environ["DATABASE_URL"] = ADMIN_URL.rsplit("/", 1)[0] + f"/{TEST_DB}"
os.environ["BASE_URL"] = "http://testserver"
os.environ["ADMIN_EMAILS"] = "admin@example.com"
os.environ["SESSION_SECRET"] = "test-secret"

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from backend import auth, models  # noqa: E402
from backend.db import SessionLocal, engine  # noqa: E402

# 테스트마다 비우는 테이블(기본 데이터인 manuals·supported_models는 남깁니다)
USER_TABLES = ["admin_audit_logs", "metric_events", "bookmarks", "request_memories", "conversation_memories", "memories",
               "checklist_events", "checklist_items", "request_events", "consultation_requests", "messages",
               "conversations", "products", "sessions", "users"]


@pytest.fixture(scope="session", autouse=True)
def database():
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {TEST_DB}")
    command.upgrade(Config("alembic.ini"), "head")
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_tables():
    yield
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(USER_TABLES) + " CASCADE"))


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def engine_fake():
    from backend.engine import FakeEngine
    return FakeEngine()


@pytest.fixture
def app(engine_fake):
    from backend.main import create_app
    app = create_app(engine_fake, background=False)
    yield app
    app.state.jobs.executor.shutdown(wait=True)


@pytest.fixture
def wait_done():
    """작업이 끝날 때까지 상태를 조회합니다(작업은 스레드에서 돕니다)."""
    def wait(client, request_id, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            body = client.get(f"/api/requests/{request_id}").json()
            if body["status"] not in ("queued", "running"):
                return body
            time.sleep(0.05)
        raise AssertionError("작업이 끝나지 않았습니다.")
    return wait


class LoggedIn:
    """로그인한 사용자의 TestClient. 상태를 바꾸는 요청에는 CSRF 헤더를 붙입니다."""

    def __init__(self, app, user, token, csrf):
        self.user, self.csrf = user, csrf
        self.client = TestClient(app, base_url="http://testserver")
        self.client.cookies.set(auth.COOKIE_NAME, token)

    def get(self, url, **kw):
        return self.client.get(url, **kw)

    def _write(self, method, url, csrf=True, **kw):
        headers = {**({"X-CSRF-Token": self.csrf} if csrf else {}), **kw.pop("headers", {})}
        return self.client.request(method, url, headers=headers, **kw)

    def post(self, url, **kw):
        return self._write("POST", url, **kw)

    def patch(self, url, **kw):
        return self._write("PATCH", url, **kw)

    def put(self, url, **kw):
        return self._write("PUT", url, **kw)

    def delete(self, url, **kw):
        return self._write("DELETE", url, **kw)


@pytest.fixture
def login(app):
    def make(email="user@example.com"):
        with SessionLocal() as s:
            user = models.User(google_sub=f"sub-{uuid.uuid4()}", email=email, name=email.split("@")[0])
            s.add(user)
            s.flush()
            token = auth.create_session(s, user)
            s.commit()
            csrf = s.query(models.Session).filter_by(user_id=user.id).one().csrf_token
        return LoggedIn(app, user, token, csrf)
    return make


@pytest.fixture
def product_of():
    def make(client, model="w10n", nickname="우리집 워시타워"):
        r = client.post("/api/products", json={"supported_model_id": model, "nickname": nickname})
        assert r.status_code == 201, r.text
        return r.json()
    return make
