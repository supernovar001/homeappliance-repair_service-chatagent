# -*- coding: utf-8 -*-
"""상담 실행 API: 질문 보내기, 점검 결과 알리기, 작업 상태·SSE, 재시도, 근거 PDF 페이지, 예시 질문."""
import asyncio
import json
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session as DbSession

from .. import models
from ..auth import Viewer, current_viewer
from ..checklist import CHECK_OUTCOMES, CHECK_STATUSES, current_answer_items, report_text
from ..db import SessionLocal, get_db, utcnow
from ..jobs import TERMINAL_EVENTS
from ..settings import settings
from . import owned, parse_id
from .conversations import ACTIVE_STATUSES, applied_memories, message_json, request_json

router = APIRouter(prefix="/api")

MAX_QUESTION_CHARS = 2000
POLL_SECONDS = 0.5
KEEPALIVE_SECONDS = 15


class MessageIn(BaseModel):
    content: str
    client_request_id: str = Field(min_length=8, max_length=64)


class ChecklistResult(BaseModel):
    item_id: str
    status: str
    outcome: str


class ChecklistResultsIn(BaseModel):
    client_request_id: str = Field(min_length=8, max_length=64)
    results: list[ChecklistResult] = Field(min_length=1, max_length=10)
    note: str = Field(default="", max_length=500)


def guard_new_request(db, viewer, conversation):
    if db.scalar(select(exists().where(models.ConsultationRequest.conversation_id == conversation.id,
                                       models.ConsultationRequest.status.in_(ACTIVE_STATUSES)))):
        raise HTTPException(409, "이전 질문의 답변을 만드는 중입니다. 답변이 끝난 뒤 보내 주세요.")
    since = utcnow() - timedelta(minutes=settings.rate_limit_minutes)
    recent = db.scalar(select(func.count()).select_from(models.ConsultationRequest).where(
        models.ConsultationRequest.user_id == viewer.user.id, models.ConsultationRequest.created_at > since))
    if recent >= settings.rate_limit_count:
        raise HTTPException(429, f"{settings.rate_limit_minutes}분에 {settings.rate_limit_count}번까지 질문할 수 있습니다. 잠시 후 다시 시도해 주세요.")


def existing_request(db, viewer, client_request_id):
    """같은 client_request_id로 다시 보낸 요청(새로고침·중복 클릭)은 새 작업을 만들지 않고 기존 작업을 돌려줍니다."""
    return db.scalar(select(models.ConsultationRequest).where(models.ConsultationRequest.user_id == viewer.user.id,
                                                             models.ConsultationRequest.client_request_id == client_request_id))


def enqueue(db, viewer, conversation, user_message, client_request_id, attempt=1):
    req = models.ConsultationRequest(user_id=viewer.user.id, conversation_id=conversation.id, client_request_id=client_request_id,
                                     user_message_id=user_message.id, attempt=attempt)
    db.add(req)
    db.flush()
    # 작업을 만들 때 실제로 넣을 기억의 내용·버전을 스냅샷으로 남깁니다(나중에 고쳐도 이 답변의 근거는 그대로 보입니다).
    for m in applied_memories(db, conversation.id):
        db.add(models.RequestMemory(request_id=req.id, memory_id=m.id, version=m.version,
                                    snapshot={"symptom": m.symptom, "action": m.action, "outcome": m.outcome}))
    conversation.last_message_at = utcnow()
    return req


def accepted(req, user_message):
    return JSONResponse({"request": request_json(req), "user_message": message_json(user_message)}, status_code=202)


@router.post("/conversations/{conversation_id}/messages")
def send_message(conversation_id: str, body: MessageIn, request: Request, viewer: Viewer = Depends(current_viewer),
                 db: DbSession = Depends(get_db)):
    conversation = owned(db, models.Conversation, conversation_id, viewer.user.id)
    content = body.content.strip()
    if not content:
        raise HTTPException(422, "질문을 입력해 주세요.")
    if len(content) > MAX_QUESTION_CHARS:
        raise HTTPException(422, f"질문은 {MAX_QUESTION_CHARS:,}자까지 보낼 수 있습니다.")
    if (old := existing_request(db, viewer, body.client_request_id)) is not None:
        if old.conversation_id != conversation.id:
            raise HTTPException(409, "다른 상담에서 쓴 요청 ID입니다.")
        return accepted(old, db.get(models.Message, old.user_message_id))
    guard_new_request(db, viewer, conversation)
    user_message = models.Message(conversation_id=conversation.id, role="user", kind="question", content=content)
    db.add(user_message)
    db.flush()
    if conversation.title == "새 상담":
        conversation.title = " ".join(content.split())[:30]
    req = enqueue(db, viewer, conversation, user_message, body.client_request_id)
    db.commit()
    request.app.state.jobs.submit(req.id)
    return accepted(req, user_message)


@router.post("/conversations/{conversation_id}/checklist-results")
def report_checklist(conversation_id: str, body: ChecklistResultsIn, request: Request, viewer: Viewer = Depends(current_viewer),
                     db: DbSession = Depends(get_db)):
    """여러 항목의 점검 결과를 한 번에 받아 '[점검 결과] …' 발화 하나와 후속 답변 작업 하나를 만듭니다."""
    conversation = owned(db, models.Conversation, conversation_id, viewer.user.id)
    if (old := existing_request(db, viewer, body.client_request_id)) is not None:
        return accepted(old, db.get(models.Message, old.user_message_id))
    items = {str(i.id): i for i in current_answer_items(db, conversation.id) if i.enabled}
    rows = []
    for r in body.results:
        item = items.get(r.item_id)
        if item is None:
            raise HTTPException(422, "가장 최근 답변의 점검 항목만 결과를 알릴 수 있습니다.")
        if r.status not in CHECK_STATUSES or r.outcome not in CHECK_OUTCOMES:
            raise HTTPException(422, "지원하지 않는 점검 상태나 결과입니다.")
        rows.append((item, r.status, r.outcome))
    guard_new_request(db, viewer, conversation)
    user_message = models.Message(conversation_id=conversation.id, role="user", kind="checklist_report", content=report_text(rows, body.note))
    db.add(user_message)
    db.flush()
    for item, status, outcome in rows:
        item.status, item.outcome = status, outcome
        db.add(models.ChecklistEvent(item_id=item.id, message_id=user_message.id, status=status, outcome=outcome, source="button"))
    req = enqueue(db, viewer, conversation, user_message, body.client_request_id)
    db.commit()
    request.app.state.jobs.submit(req.id)
    return accepted(req, user_message)


@router.get("/requests/{request_id}")
def get_request(request_id: str, viewer: Viewer = Depends(current_viewer), db: DbSession = Depends(get_db)):
    return request_json(owned(db, models.ConsultationRequest, request_id, viewer.user.id))


@router.post("/requests/{request_id}/retry")
def retry_request(request_id: str, request: Request, viewer: Viewer = Depends(current_viewer), db: DbSession = Depends(get_db)):
    """실패하거나 중단된 작업을 같은 고객 발화로 다시 실행합니다."""
    old = owned(db, models.ConsultationRequest, request_id, viewer.user.id)
    if old.status not in ("failed", "interrupted"):
        raise HTTPException(409, "실패하거나 중단된 답변만 다시 시도할 수 있습니다.")
    conversation = db.get(models.Conversation, old.conversation_id)
    newest = db.scalar(select(models.ConsultationRequest.id).where(models.ConsultationRequest.conversation_id == conversation.id)
                       .order_by(models.ConsultationRequest.created_at.desc()).limit(1))
    if newest != old.id:
        raise HTTPException(409, "가장 최근 질문만 다시 시도할 수 있습니다.")
    guard_new_request(db, viewer, conversation)
    user_message = db.get(models.Message, old.user_message_id)
    req = enqueue(db, viewer, conversation, user_message, f"retry-{uuid.uuid4()}", attempt=old.attempt + 1)
    db.commit()
    request.app.state.jobs.submit(req.id)
    return accepted(req, user_message)


def _events_after(request_id, after):
    with SessionLocal() as db:
        return [(e.seq, e.type, e.data) for e in db.scalars(
            select(models.RequestEvent).where(models.RequestEvent.request_id == request_id, models.RequestEvent.seq > after)
            .order_by(models.RequestEvent.seq))]


@router.get("/requests/{request_id}/events")
async def request_events(request_id: str, request: Request, last_event_id: str | None = Header(default=None),
                         after: int | None = Query(default=None), viewer: Viewer = Depends(current_viewer),
                         db: DbSession = Depends(get_db)):
    """진행 단계를 SSE로 보냅니다. 다시 연결하면 Last-Event-ID 다음 이벤트부터 보냅니다."""
    req = owned(db, models.ConsultationRequest, request_id, viewer.user.id)
    db.close()  # 스트림이 열려 있는 동안 DB 연결을 붙잡지 않습니다.
    start = after if after is not None else int(last_event_id) if (last_event_id or "").isdigit() else 0

    async def stream():
        seen, idle = start, 0.0
        yield "retry: 2000\n\n"
        while not await request.is_disconnected():
            for seq, type_, data in await run_in_threadpool(_events_after, req.id, seen):
                seen = seq
                yield f"id: {seq}\nevent: {type_}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                if type_ in TERMINAL_EVENTS:
                    return
                idle = 0.0
            await asyncio.sleep(POLL_SECONDS)
            idle += POLL_SECONDS
            if idle >= KEEPALIVE_SECONDS:
                yield ": keepalive\n\n"
                idle = 0.0

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/manuals/{manual_id}/pages/{page}")
async def manual_page(manual_id: str, page: int, request: Request, message_id: str | None = None,
                      viewer: Viewer = Depends(current_viewer), db: DbSession = Depends(get_db)):
    """설명서 페이지 이미지. message_id를 주면 그 답변이 근거로 쓴 문단을 형광펜으로 표시합니다."""
    manual = db.get(models.Manual, manual_id)
    if manual is None or page not in manual.allowed_pages:
        raise HTTPException(404, "볼 수 없는 페이지입니다.")
    highlights = ()
    if message_id:
        message = db.get(models.Message, parse_id(message_id))
        conversation = message and db.get(models.Conversation, message.conversation_id)
        if conversation is None or conversation.user_id != viewer.user.id:
            raise HTTPException(404, "찾을 수 없습니다.")
        highlights = tuple((message.result or {}).get("evidence_texts", {}).get(str(page), []))
    png = await run_in_threadpool(request.app.state.engine.page_png, page, highlights)
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})


@router.get("/examples")
def examples(request: Request, viewer: Viewer = Depends(current_viewer)):
    return request.app.state.engine.examples()
