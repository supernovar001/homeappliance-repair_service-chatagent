# -*- coding: utf-8 -*-
"""보관 기간 정리. 서버 시작 시와 6시간마다 실행합니다.

- 마지막 대화로부터 RETENTION_DAYS(기본 90일)가 지난 상담을 지웁니다.
  메시지·작업·이벤트·체크리스트·북마크는 함께 지워지고(외래키 CASCADE),
  확인된 기억은 남기되 출처 상담 연결만 끊깁니다(외래키 SET NULL). 확인하지 않은 초안은 지웁니다.
- 만료된 로그인 세션을 지웁니다.
"""
import asyncio
from datetime import timedelta

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import delete, select

from . import models
from .db import SessionLocal, utcnow
from .settings import settings

INTERVAL_SECONDS = 6 * 3600


def purge(db, now=None):
    now = now or utcnow()
    cutoff = now - timedelta(days=settings.retention_days)
    expired = list(db.scalars(select(models.Conversation.id).where(models.Conversation.last_message_at < cutoff)))
    if expired:
        db.execute(delete(models.Memory).where(models.Memory.source_conversation_id.in_(expired), models.Memory.status == "draft"))
        db.execute(delete(models.Conversation).where(models.Conversation.id.in_(expired)))
    sessions = db.execute(delete(models.Session).where(models.Session.expires_at < now)).rowcount
    db.commit()
    return {"conversations": len(expired), "sessions": sessions}


def purge_once():
    with SessionLocal() as db:
        return purge(db)


async def run_forever():
    while True:
        try:
            result = await run_in_threadpool(purge_once)
            if any(result.values()):
                print(f"보관 기간 정리: 상담 {result['conversations']}건, 세션 {result['sessions']}건 삭제")
        except Exception as exc:  # 정리 실패로 서버가 멈추지 않게 하고 다음 주기에 다시 시도합니다.
            print(f"보관 기간 정리 실패: {exc!r}")
        await asyncio.sleep(INTERVAL_SECONDS)
