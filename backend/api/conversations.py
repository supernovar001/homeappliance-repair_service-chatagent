# -*- coding: utf-8 -*-
"""상담 목록·생성·상세·제목 변경·삭제 API."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, exists, func, or_, select, update
from sqlalchemy.orm import Session as DbSession

from .. import models
from ..auth import Viewer, current_viewer
from ..db import get_db
from . import iso, owned, parse_id

router = APIRouter(prefix="/api")

MEMORY_APPLY_LIMIT = 10  # 상담 하나에 넣는 기억 수(최근 수정순)
ACTIVE_STATUSES = ("queued", "running")


def memory_json(m):
    return {"id": str(m.id), "symptom": m.symptom, "action": m.action, "outcome": m.outcome, "evidence": m.evidence,
            "status": m.status, "version": m.version, "source_conversation_id": str(m.source_conversation_id) if m.source_conversation_id else None,
            "confirmed_at": iso(m.confirmed_at), "updated_at": iso(m.updated_at)}


def applied_memories(db, conversation_id):
    """이번 상담에 실제로 넣을 기억: 선택된 확인된 기억 중 최근 수정순 10개."""
    return list(db.scalars(
        select(models.Memory).join(models.ConversationMemory, models.ConversationMemory.memory_id == models.Memory.id)
        .where(models.ConversationMemory.conversation_id == conversation_id, models.Memory.status == "confirmed")
        .order_by(models.Memory.updated_at.desc()).limit(MEMORY_APPLY_LIMIT)))


def checklist_json(c):
    return {"id": str(c.id), "message_id": str(c.message_id), "key": c.key, "title": c.title, "detail": c.detail, "pages": c.pages,
            "kind": c.kind, "enabled": c.enabled, "status": c.status, "outcome": c.outcome,
            "inherited": c.inherited_from_item_id is not None}


def request_json(r):
    return {"id": str(r.id), "status": r.status, "stage": r.stage, "error_type": r.error_type, "attempt": r.attempt,
            "user_message_id": str(r.user_message_id), "assistant_message_id": str(r.assistant_message_id) if r.assistant_message_id else None,
            "created_at": iso(r.created_at), "finished_at": iso(r.finished_at)}


def message_json(m, bookmarked=False, memories=None):
    return {"id": str(m.id), "role": m.role, "kind": m.kind, "content": m.content, "result": m.result,
            "created_at": iso(m.created_at), "bookmarked": bookmarked, "applied_memories": memories or []}


def conversation_summary(c, product):
    return {"id": str(c.id), "title": c.title, "product_id": str(c.product_id), "product_nickname": product.nickname,
            "created_at": iso(c.created_at), "last_message_at": iso(c.last_message_at)}


def latest_request(db, conversation_id):
    return db.scalar(select(models.ConsultationRequest).where(models.ConsultationRequest.conversation_id == conversation_id)
                     .order_by(models.ConsultationRequest.created_at.desc()).limit(1))


def conversation_detail(db, viewer, c):
    product = db.get(models.Product, c.product_id)
    messages = list(db.scalars(select(models.Message).where(models.Message.conversation_id == c.id).order_by(models.Message.created_at)))
    bookmarked = set(db.scalars(select(models.Bookmark.message_id).where(
        models.Bookmark.user_id == viewer.user.id, models.Bookmark.message_id.in_([m.id for m in messages]))))
    # 답변마다 그 작업에 실제로 넣은 기억(스냅샷)을 붙입니다. 지운 기억은 내용 없이 '삭제된 기억'으로 표시합니다.
    snapshots = {}
    rows = db.execute(select(models.ConsultationRequest.assistant_message_id, models.RequestMemory)
                      .join(models.RequestMemory, models.RequestMemory.request_id == models.ConsultationRequest.id)
                      .where(models.ConsultationRequest.conversation_id == c.id, models.ConsultationRequest.assistant_message_id.is_not(None)))
    for message_id, rm in rows:
        snapshots.setdefault(message_id, []).append({"memory_id": str(rm.memory_id) if rm.memory_id else None, "version": rm.version,
                                                     "deleted": rm.deleted, **({} if rm.deleted or not rm.snapshot else rm.snapshot)})
    selected = set(db.scalars(select(models.ConversationMemory.memory_id).where(models.ConversationMemory.conversation_id == c.id)))
    confirmed = list(db.scalars(select(models.Memory).where(models.Memory.product_id == c.product_id, models.Memory.status == "confirmed")
                                .order_by(models.Memory.updated_at.desc())))
    checklist = db.scalars(select(models.ChecklistItem).where(models.ChecklistItem.conversation_id == c.id)
                           .order_by(models.ChecklistItem.created_at, models.ChecklistItem.position))
    request = latest_request(db, c.id)
    return {
        **conversation_summary(c, product),
        "product": {"id": str(product.id), "nickname": product.nickname, "supported_model_id": product.supported_model_id},
        "messages": [message_json(m, m.id in bookmarked, snapshots.get(m.id)) for m in messages],
        "checklist": [checklist_json(i) for i in checklist],
        "memories": [{**memory_json(m), "selected": m.id in selected} for m in confirmed],
        "will_apply": [str(m.id) for m in applied_memories(db, c.id)],
        "source_memory_count": db.scalar(select(func.count()).select_from(models.Memory).where(models.Memory.source_conversation_id == c.id)),
        "request": request_json(request) if request else None,
    }


class ConversationIn(BaseModel):
    product_id: str


class ConversationPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    product_id: str | None = None


@router.get("/conversations")
def list_conversations(q: str = Query("", max_length=100), product_id: str | None = None, limit: int = Query(30, ge=1, le=100),
                       offset: int = Query(0, ge=0), viewer: Viewer = Depends(current_viewer), db: DbSession = Depends(get_db)):
    stmt = (select(models.Conversation, models.Product).join(models.Product, models.Product.id == models.Conversation.product_id)
            .where(models.Conversation.user_id == viewer.user.id))
    if product_id:
        stmt = stmt.where(models.Conversation.product_id == parse_id(product_id))
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(models.Conversation.title.ilike(like), exists().where(
            models.Message.conversation_id == models.Conversation.id, models.Message.content.ilike(like))))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(stmt.order_by(models.Conversation.last_message_at.desc()).limit(limit).offset(offset)).all()
    return {"items": [conversation_summary(c, p) for c, p in rows], "total": total}


@router.post("/conversations", status_code=201)
def create_conversation(body: ConversationIn, viewer: Viewer = Depends(current_viewer), db: DbSession = Depends(get_db)):
    product = owned(db, models.Product, body.product_id, viewer.user.id)
    conversation = models.Conversation(user_id=viewer.user.id, product_id=product.id)
    db.add(conversation)
    db.flush()
    # 그 제품의 확인된 기억을 모두 선택한 상태로 시작합니다.
    for memory_id in db.scalars(select(models.Memory.id).where(models.Memory.product_id == product.id, models.Memory.status == "confirmed")):
        db.add(models.ConversationMemory(conversation_id=conversation.id, memory_id=memory_id))
    db.add(models.MetricEvent(type="conversation_created"))
    db.commit()
    return conversation_detail(db, viewer, conversation)


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, viewer: Viewer = Depends(current_viewer), db: DbSession = Depends(get_db)):
    return conversation_detail(db, viewer, owned(db, models.Conversation, conversation_id, viewer.user.id))


@router.patch("/conversations/{conversation_id}")
def update_conversation(conversation_id: str, body: ConversationPatch, viewer: Viewer = Depends(current_viewer), db: DbSession = Depends(get_db)):
    c = owned(db, models.Conversation, conversation_id, viewer.user.id)
    if body.title is not None:
        if not body.title.strip():
            raise HTTPException(422, "제목을 입력해 주세요.")
        c.title = body.title.strip()
    if body.product_id is not None and parse_id(body.product_id) != c.product_id:
        product = owned(db, models.Product, body.product_id, viewer.user.id)
        if db.scalar(select(exists().where(models.Message.conversation_id == c.id))):
            raise HTTPException(409, "대화가 시작된 상담은 제품을 바꿀 수 없습니다. 새 상담을 시작해 주세요.")
        c.product_id = product.id
        db.execute(delete(models.ConversationMemory).where(models.ConversationMemory.conversation_id == c.id))
        for memory_id in db.scalars(select(models.Memory.id).where(models.Memory.product_id == product.id, models.Memory.status == "confirmed")):
            db.add(models.ConversationMemory(conversation_id=c.id, memory_id=memory_id))
    db.commit()
    return conversation_detail(db, viewer, c)


def scrub_memory_snapshots(db, memory_ids):
    """지운 기억은 다른 상담의 작업 스냅샷에서도 내용을 비우고 '삭제된 기억'으로 표시합니다."""
    if memory_ids:
        db.execute(update(models.RequestMemory).where(models.RequestMemory.memory_id.in_(memory_ids))
                   .values(deleted=True, snapshot=None))


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str, viewer: Viewer = Depends(current_viewer), db: DbSession = Depends(get_db)):
    c = owned(db, models.Conversation, conversation_id, viewer.user.id)
    if db.scalar(select(exists().where(models.ConsultationRequest.conversation_id == c.id,
                                       models.ConsultationRequest.status.in_(ACTIVE_STATUSES)))):
        raise HTTPException(409, "답변을 만드는 중에는 상담을 지울 수 없습니다.")
    # 사용자가 직접 지우면 이 상담에서 나온 기억도 함께 지웁니다(보관 기간 삭제와 다름: 그때는 기억을 남깁니다).
    memory_ids = list(db.scalars(select(models.Memory.id).where(models.Memory.source_conversation_id == c.id)))
    scrub_memory_snapshots(db, memory_ids)
    if memory_ids:
        db.execute(delete(models.Memory).where(models.Memory.id.in_(memory_ids)))
    db.delete(c)
    db.commit()
