# -*- coding: utf-8 -*-
"""기억 API: 초안 만들기, 확인·수정, 삭제, 제품별 목록, 상담별 적용 선택."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from .. import models
from ..auth import Viewer, current_viewer
from ..db import get_db, utcnow
from . import owned, parse_id
from .conversations import ACTIVE_STATUSES, conversation_detail, memory_json, scrub_memory_snapshots

router = APIRouter(prefix="/api")

MEMORY_OUTCOMES = ("해결됨", "해결되지 않음", "결과 미확인")


class MemoryPatch(BaseModel):
    symptom: str = Field(min_length=1, max_length=200)
    action: str = Field(min_length=1, max_length=300)
    outcome: str
    confirm: bool = False


class SelectionIn(BaseModel):
    memory_ids: list[str] = Field(max_length=100)


@router.post("/conversations/{conversation_id}/memory-drafts")
async def make_drafts(conversation_id: str, request: Request, viewer: Viewer = Depends(current_viewer), db: DbSession = Depends(get_db)):
    """고객 발화만 AI에 넣어 '증상·수행한 조치·결과' 초안을 만듭니다. 같은 상담의 이전 초안은 새 초안으로 바꿉니다."""
    c = owned(db, models.Conversation, conversation_id, viewer.user.id)
    utterances = list(db.scalars(select(models.Message.content).where(models.Message.conversation_id == c.id, models.Message.role == "user")
                                 .order_by(models.Message.created_at)))
    if not utterances:
        raise HTTPException(422, "아직 대화가 없어 기억을 만들 수 없습니다.")
    try:
        drafts = await run_in_threadpool(request.app.state.engine.draft_memories, utterances)
    except Exception:
        raise HTTPException(502, "기억 초안을 만들지 못했습니다. 잠시 후 다시 시도해 주세요.")
    db.execute(delete(models.Memory).where(models.Memory.source_conversation_id == c.id, models.Memory.status == "draft"))
    rows = [models.Memory(user_id=viewer.user.id, product_id=c.product_id, source_conversation_id=c.id, symptom=d["symptom"][:200],
                          action=d["action"][:300], outcome=d["outcome"], evidence=d["evidence"], status="draft") for d in drafts]
    db.add_all(rows)
    db.commit()
    return [memory_json(m) for m in rows]


@router.patch("/memories/{memory_id}")
def update_memory(memory_id: str, body: MemoryPatch, viewer: Viewer = Depends(current_viewer), db: DbSession = Depends(get_db)):
    """초안을 확인하거나(confirm) 확인된 기억을 고칩니다. 확인된 기억의 내용을 고치면 버전이 올라갑니다."""
    m = owned(db, models.Memory, memory_id, viewer.user.id)
    if body.outcome not in MEMORY_OUTCOMES:
        raise HTTPException(422, "지원하지 않는 결과입니다.")
    symptom, action = body.symptom.strip(), body.action.strip()
    if not symptom or not action:
        raise HTTPException(422, "증상과 수행한 조치를 입력해 주세요.")
    changed = (symptom, action, body.outcome) != (m.symptom, m.action, m.outcome)
    if m.status == "confirmed" and changed:
        m.version += 1
    m.symptom, m.action, m.outcome, m.updated_at = symptom, action, body.outcome, utcnow()
    if m.status == "draft" and body.confirm:
        m.status, m.confirmed_at = "confirmed", utcnow()
    db.commit()
    return memory_json(m)


@router.delete("/memories/{memory_id}", status_code=204)
def delete_memory(memory_id: str, viewer: Viewer = Depends(current_viewer), db: DbSession = Depends(get_db)):
    """기억을 지우면 선택 목록에서 빠지고, 지난 답변의 스냅샷도 내용을 비워 '삭제된 기억'으로 표시합니다."""
    m = owned(db, models.Memory, memory_id, viewer.user.id)
    scrub_memory_snapshots(db, [m.id])
    db.delete(m)
    db.commit()


@router.get("/products/{product_id}/memories")
def product_memories(product_id: str, viewer: Viewer = Depends(current_viewer), db: DbSession = Depends(get_db)):
    p = owned(db, models.Product, product_id, viewer.user.id)
    rows = db.scalars(select(models.Memory).where(models.Memory.product_id == p.id)
                      .order_by(models.Memory.status.desc(), models.Memory.updated_at.desc()))  # draft가 먼저
    return [memory_json(m) for m in rows]


@router.put("/conversations/{conversation_id}/memory-selection")
def select_memories(conversation_id: str, body: SelectionIn, viewer: Viewer = Depends(current_viewer), db: DbSession = Depends(get_db)):
    """이 상담에 적용할 기억을 고릅니다. 같은 사용자·같은 제품의 확인된 기억만 고를 수 있습니다."""
    c = owned(db, models.Conversation, conversation_id, viewer.user.id)
    if db.scalar(select(models.ConsultationRequest.id).where(models.ConsultationRequest.conversation_id == c.id,
                                                             models.ConsultationRequest.status.in_(ACTIVE_STATUSES)).limit(1)):
        raise HTTPException(409, "답변을 만드는 중에는 기억을 바꿀 수 없습니다.")
    ids = {parse_id(x) for x in body.memory_ids}
    valid = set(db.scalars(select(models.Memory.id).where(models.Memory.id.in_(ids), models.Memory.user_id == viewer.user.id,
                                                          models.Memory.product_id == c.product_id, models.Memory.status == "confirmed")))
    if valid != ids:
        raise HTTPException(422, "이 상담의 제품에 확인된 기억만 고를 수 있습니다.")
    db.execute(delete(models.ConversationMemory).where(models.ConversationMemory.conversation_id == c.id))
    db.add_all([models.ConversationMemory(conversation_id=c.id, memory_id=i) for i in ids])
    db.commit()
    return conversation_detail(db, viewer, c)
