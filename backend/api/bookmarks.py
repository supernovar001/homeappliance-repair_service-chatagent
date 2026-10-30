# -*- coding: utf-8 -*-
"""북마크 API. AI 답변만 저장할 수 있고, 목록에는 답변과 그 직전 질문을 함께 보여 줍니다."""
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as DbSession

from .. import models
from ..auth import Viewer, current_viewer
from ..db import get_db
from . import iso, parse_id

router = APIRouter(prefix="/api")


def owned_answer(db, viewer, message_id):
    message = db.get(models.Message, parse_id(message_id))
    conversation = message and db.get(models.Conversation, message.conversation_id)
    if conversation is None or conversation.user_id != viewer.user.id:
        raise HTTPException(404, "찾을 수 없습니다.")
    if message.kind != "answer":
        raise HTTPException(422, "AI 답변만 북마크할 수 있습니다.")
    return message


@router.put("/messages/{message_id}/bookmark", status_code=204)
def add_bookmark(message_id: str, viewer: Viewer = Depends(current_viewer), db: DbSession = Depends(get_db)):
    message = owned_answer(db, viewer, message_id)
    if db.get(models.Bookmark, (viewer.user.id, message.id)) is None:
        db.add(models.Bookmark(user_id=viewer.user.id, message_id=message.id))
        db.commit()
    return Response(status_code=204)


@router.delete("/messages/{message_id}/bookmark", status_code=204)
def remove_bookmark(message_id: str, viewer: Viewer = Depends(current_viewer), db: DbSession = Depends(get_db)):
    message = owned_answer(db, viewer, message_id)
    if (row := db.get(models.Bookmark, (viewer.user.id, message.id))) is not None:
        db.delete(row)
        db.commit()
    return Response(status_code=204)


@router.get("/bookmarks")
def list_bookmarks(q: str = Query("", max_length=100), product_id: str | None = None, page: int = Query(1, ge=1),
                   size: int = Query(10, ge=1, le=50), viewer: Viewer = Depends(current_viewer), db: DbSession = Depends(get_db)):
    stmt = (select(models.Bookmark, models.Message, models.Conversation, models.Product)
            .join(models.Message, models.Message.id == models.Bookmark.message_id)
            .join(models.Conversation, models.Conversation.id == models.Message.conversation_id)
            .join(models.Product, models.Product.id == models.Conversation.product_id)
            .where(models.Bookmark.user_id == viewer.user.id))
    if product_id:
        stmt = stmt.where(models.Conversation.product_id == parse_id(product_id))
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(models.Message.content.ilike(like), models.Conversation.title.ilike(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(stmt.order_by(models.Bookmark.created_at.desc()).limit(size).offset((page - 1) * size)).all()
    items = []
    for b, m, c, p in rows:
        asked = db.scalar(select(models.Message.content).where(models.Message.conversation_id == c.id, models.Message.role == "user",
                                                               models.Message.created_at < m.created_at)
                          .order_by(models.Message.created_at.desc()).limit(1))
        checklist = db.scalar(select(func.count()).select_from(models.ChecklistItem).where(models.ChecklistItem.message_id == m.id))
        items.append({"message_id": str(m.id), "conversation_id": str(c.id), "conversation_title": c.title,
                      "product_id": str(p.id), "product_nickname": p.nickname, "question": asked or "", "answer": m.content,
                      "route": (m.result or {}).get("route"), "evidence_pages": (m.result or {}).get("evidence_pages", []),
                      "checklist_count": checklist, "answered_at": iso(m.created_at), "saved_at": iso(b.created_at)})
    return {"items": items, "total": total, "page": page, "size": size}
