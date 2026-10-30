# -*- coding: utf-8 -*-
"""화면 검사(Playwright)용 서버. 가짜 엔진과 예시 데이터로 빌드한 Vue 화면을 띄웁니다.

  docker compose up -d db && (cd frontend && npm run build)
  python tests/e2e_server.py          # http://localhost:8001, 세션 쿠키 wc_session=e2e-admin-token

washcare_e2e DB를 새로 만들고 관리자 사용자의 세션을 직접 넣습니다(앱 코드에는 로그인 우회가 없습니다).
"""
import os
import sys
import uuid
from datetime import timedelta
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
ADMIN_URL = os.getenv("TEST_ADMIN_DATABASE_URL", "postgresql://washcare:washcare@localhost:5433/washcare")
os.environ["DATABASE_URL"] = ADMIN_URL.rsplit("/", 1)[0] + "/washcare_e2e"
os.environ.update(BASE_URL="http://localhost:8001", ADMIN_EMAILS="admin@example.com", SESSION_SECRET="e2e")
TOKEN = "e2e-admin-token"


def reset_db():
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute("DROP DATABASE IF EXISTS washcare_e2e WITH (FORCE)")
        conn.execute("CREATE DATABASE washcare_e2e")
    from alembic import command
    from alembic.config import Config
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")


def seed(engine):
    from backend import models
    from backend.auth import hash_token
    from backend.db import SessionLocal, utcnow
    from backend.jobs import JobRunner

    with SessionLocal() as db:
        user = models.User(google_sub="e2e", email="admin@example.com", name="홍길동")
        db.add(user)
        db.flush()
        db.add(models.Session(user_id=user.id, token_hash=hash_token(TOKEN), csrf_token="e2e-csrf", expires_at=utcnow() + timedelta(days=1)))
        home = models.Product(user_id=user.id, supported_model_id="w10n", nickname="우리집 워시타워")
        parents = models.Product(user_id=user.id, supported_model_id="w1310n", nickname="부모님댁 워시타워", model_code="W1310ABN")
        db.add_all([home, parents])
        db.flush()
        db.add(models.Memory(user_id=user.id, product_id=home.id, symptom="OE 표시, 물이 안 빠짐", action="배수 호스를 바로 놓음",
                             outcome="해결됨", status="confirmed", confirmed_at=utcnow()))
        conv = models.Conversation(user_id=user.id, product_id=home.id, title="OE 표시, 물이 남아 있어요")
        db.add(conv)
        db.flush()
        for m in db.query(models.Memory).all():
            db.add(models.ConversationMemory(conversation_id=conv.id, memory_id=m.id))
        question = models.Message(conversation_id=conv.id, role="user", kind="question",
                                  content="빨래가 끝날 시간이 지났는데 멈춰 있어요. 화면에 OE라고 나오고 물이 남아 있어요. 어제 배수 호스를 옆으로 옮겼어요.")
        db.add(question)
        db.flush()
        req = models.ConsultationRequest(user_id=user.id, conversation_id=conv.id, client_request_id="e2e-1", user_message_id=question.id)
        db.add(req)
        db.add(models.MetricEvent(type="conversation_created"))
        db.commit()
        conv_id, req_id = conv.id, req.id
    JobRunner(engine, 1, 60).run(req_id)
    with SessionLocal() as db:
        answer = db.query(models.Message).filter_by(conversation_id=conv_id, kind="answer").one()
        db.add(models.Bookmark(user_id=db.query(models.User).one().id, message_id=answer.id))
        db.commit()
    (ROOT / "frontend" / "test-results").mkdir(parents=True, exist_ok=True)
    (ROOT / "frontend" / "test-results" / "e2e-ids.txt").write_text(str(conv_id))


if __name__ == "__main__":
    import uvicorn

    reset_db()
    from backend.engine import FakeEngine
    from backend.main import create_app

    fake = FakeEngine()
    seed(fake)
    uvicorn.run(create_app(fake, background=False), host="127.0.0.1", port=8001, log_level="warning")
