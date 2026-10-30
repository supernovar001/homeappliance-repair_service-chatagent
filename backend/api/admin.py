# -*- coding: utf-8 -*-
"""관리자 API. 메뉴를 숨기는 것과 별개로 서버에서 ADMIN_EMAILS를 검사합니다(admin_viewer).

통계는 개인정보가 없는 metric_events로 계산합니다. 기간은 한국 시간 기준 날짜입니다.
상담 원문을 열 때마다 admin_audit_logs에 남깁니다.
"""
from datetime import datetime, time, timedelta
from statistics import median
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from .. import models
from ..auth import Viewer, admin_viewer
from ..db import get_db, utcnow
from . import iso, parse_id

router = APIRouter(prefix="/api/admin")
KST = ZoneInfo("Asia/Seoul")
ROUTES = ["자가 점검 우선", "서비스 기사 점검 권장", "추가 확인 필요", "상담 범위 외"]


def mask_email(email):
    local, _, domain = email.partition("@")
    return f"{local[:2]}{'*' * max(3, len(local) - 2)}@{domain}"


def p95(values):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]


def period_stats(db, start, end):
    rows = db.execute(select(models.MetricEvent).where(models.MetricEvent.created_at >= start, models.MetricEvent.created_at < end)).scalars().all()
    ok = [r for r in rows if r.type == "request_succeeded"]
    failed = [r for r in rows if r.type == "request_failed"]
    durations = [r.duration_ms for r in ok if r.duration_ms is not None]
    return rows, {
        "conversations": sum(r.type == "conversation_created" for r in rows),
        "answers": len(ok), "errors": len(failed),
        "median_ms": int(median(durations)) if durations else None, "p95_ms": p95(durations),
    }


@router.get("/stats")
def stats(days: int = Query(7, ge=1, le=90), viewer: Viewer = Depends(admin_viewer), db: DbSession = Depends(get_db)):
    today = utcnow().astimezone(KST).date()
    first = today - timedelta(days=days - 1)
    start = datetime.combine(first, time(), KST)
    end = datetime.combine(today + timedelta(days=1), time(), KST)
    rows, current = period_stats(db, start, end)
    _, previous = period_stats(db, start - timedelta(days=days), start)
    ok = [r for r in rows if r.type == "request_succeeded"]
    daily = {first + timedelta(days=i): 0 for i in range(days)}
    for r in ok:
        daily[r.created_at.astimezone(KST).date()] += 1
    errors = {}
    for r in rows:
        if r.type == "request_failed":
            errors[r.error_type or "internal"] = errors.get(r.error_type or "internal", 0) + 1
    return {
        "from": first.isoformat(), "to": today.isoformat(), "days": days, "has_data": bool(rows),
        "current": current, "previous": previous,
        "daily_answers": [{"date": d.isoformat(), "count": n} for d, n in daily.items()],
        "routes": [{"route": route, "count": sum(r.route == route for r in ok)} for route in ROUTES],
        "error_types": [{"error_type": k, "count": v} for k, v in sorted(errors.items(), key=lambda kv: -kv[1])],
    }


@router.get("/conversations")
def conversations(page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100), viewer: Viewer = Depends(admin_viewer),
                  db: DbSession = Depends(get_db)):
    stmt = (select(models.Conversation, models.User, models.Product)
            .join(models.User, models.User.id == models.Conversation.user_id)
            .join(models.Product, models.Product.id == models.Conversation.product_id))
    total = db.scalar(select(func.count()).select_from(models.Conversation))
    items = []
    for c, u, p in db.execute(stmt.order_by(models.Conversation.last_message_at.desc()).limit(size).offset((page - 1) * size)):
        last = db.scalar(select(models.Message.result).where(models.Message.conversation_id == c.id, models.Message.kind == "answer")
                         .order_by(models.Message.created_at.desc()).limit(1))
        count = db.scalar(select(func.count()).select_from(models.Message).where(models.Message.conversation_id == c.id))
        failed = db.scalar(select(func.count()).select_from(models.ConsultationRequest).where(
            models.ConsultationRequest.conversation_id == c.id, models.ConsultationRequest.status.in_(("failed", "interrupted"))))
        items.append({"id": str(c.id), "user": mask_email(u.email), "series": p.supported_model_id, "message_count": count,
                      "last_route": (last or {}).get("route"), "error_code": (last or {}).get("error_code"), "failed_requests": failed,
                      "created_at": iso(c.created_at), "last_message_at": iso(c.last_message_at)})
    return {"items": items, "total": total, "page": page, "size": size}


@router.get("/conversations/{conversation_id}")
def conversation(conversation_id: str, viewer: Viewer = Depends(admin_viewer), db: DbSession = Depends(get_db)):
    c = db.get(models.Conversation, parse_id(conversation_id))
    if c is None:
        raise HTTPException(404, "찾을 수 없습니다.")
    db.add(models.AdminAuditLog(admin_user_id=viewer.user.id, action="view_conversation", target_id=str(c.id)))
    db.commit()
    user, product = db.get(models.User, c.user_id), db.get(models.Product, c.product_id)
    messages = db.scalars(select(models.Message).where(models.Message.conversation_id == c.id).order_by(models.Message.created_at))
    requests = db.scalars(select(models.ConsultationRequest).where(models.ConsultationRequest.conversation_id == c.id)
                          .order_by(models.ConsultationRequest.created_at))
    return {
        "id": str(c.id), "user": mask_email(user.email), "series": product.supported_model_id, "created_at": iso(c.created_at),
        "last_message_at": iso(c.last_message_at),
        "messages": [{"id": str(m.id), "role": m.role, "kind": m.kind, "content": m.content, "result": m.result, "created_at": iso(m.created_at)}
                     for m in messages],
        "requests": [{"id": str(r.id), "status": r.status, "attempt": r.attempt, "error_type": r.error_type, "created_at": iso(r.created_at),
                      "duration_ms": int((r.finished_at - r.created_at).total_seconds() * 1000) if r.finished_at else None} for r in requests],
    }
