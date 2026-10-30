# -*- coding: utf-8 -*-
"""상담 작업 실행. 요청은 바로 202로 돌려주고, 작업은 스레드에서 돌리며 진행 단계를 request_events에 남깁니다.

- 동시에 도는 작업 수는 MAX_CONCURRENT_CONSULTS(기본 2)로 제한합니다. 재정렬 모델이 CPU를 많이 씁니다.
- 작업 전체 제한 시간(기본 240초)은 단계가 바뀔 때마다 확인합니다. 각 OpenAI 호출은 OPENAI_TIMEOUT으로 끊깁니다.
- 서버가 다시 시작되면 이전 프로세스에서 끝나지 않은 작업을 interrupted(재시도 가능)로 정리합니다.
"""
import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func, select

from . import models
from .checklist import facts_for_ai, save_answer_items
from .db import SessionLocal, utcnow

TERMINAL_EVENTS = ("done", "error")
ERROR_MESSAGES = {
    "timeout": "답변을 만드는 데 시간이 너무 오래 걸렸습니다. 다시 시도해 주세요.",
    "openai": "AI 서비스에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    "internal": "답변을 만들지 못했습니다. 다시 시도해 주세요.",
    "interrupted": "서버가 다시 시작되어 답변이 중단되었습니다. 다시 시도해 주세요.",
}


class JobTimeout(Exception):
    pass


def add_event(db, request_id, type_, data):
    seq = (db.scalar(select(func.max(models.RequestEvent.seq)).where(models.RequestEvent.request_id == request_id)) or 0) + 1
    db.add(models.RequestEvent(request_id=request_id, seq=seq, type=type_, data=data))
    return seq


def error_type_of(exc):
    if isinstance(exc, JobTimeout):
        return "timeout"
    try:
        import openai
        if isinstance(exc, openai.APITimeoutError):
            return "timeout"
        if isinstance(exc, openai.APIError):
            return "openai"
    except ImportError:
        pass
    return "internal"


def history_before(db, user_message):
    rows = db.scalars(select(models.Message).where(models.Message.conversation_id == user_message.conversation_id,
                                                   models.Message.created_at < user_message.created_at)
                      .order_by(models.Message.created_at))
    return [{"role": m.role, "content": m.content} for m in rows]


def answer_record(engine, result, duration_ms):
    """답변 메시지에 저장할 판단·근거 정보. 검색 문맥 전문은 저장하지 않고 근거 페이지의 문단만 남깁니다(PDF 형광펜용)."""
    pages, basis = engine.evidence_pages(result) if result["retrieved_pages"] else ([], "")
    texts = {}
    for d in result.get("contexts", []):
        texts.setdefault(d["page"], []).append(d["text"][:800])
    return {
        "route": result["route"], "reason": result["decision_reason"], "scope": result.get("scope"),
        "symptom": result.get("symptom", ""), "error_code": result.get("error_code"),
        "evidence_pages": pages, "evidence_basis": basis,
        "evidence_texts": {str(p): texts.get(p, [])[:2] for p in pages},
        "retrieved_pages": result["retrieved_pages"], "revision_failed": result.get("revision_failed", False),
        "safety_notes_added": bool(result.get("safety_notes_added")), "duration_ms": duration_ms,
    }


class JobRunner:
    def __init__(self, engine, max_workers, timeout_seconds, session_factory=SessionLocal):
        self.engine, self.timeout, self.session_factory = engine, timeout_seconds, session_factory
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="consult")

    def submit(self, request_id):
        return self.executor.submit(self.run, request_id)

    def shutdown(self):
        self.executor.shutdown(wait=False, cancel_futures=True)

    def recover(self):
        """이전 프로세스에서 끝나지 않은 작업을 중단됨으로 표시합니다."""
        with self.session_factory() as db:
            for req in db.scalars(select(models.ConsultationRequest).where(models.ConsultationRequest.status.in_(("queued", "running")))):
                req.status, req.error_type, req.finished_at = "interrupted", "interrupted", utcnow()
                add_event(db, req.id, "error", {"error_type": "interrupted", "message": ERROR_MESSAGES["interrupted"], "retryable": True})
                db.flush()
            db.commit()

    def run(self, request_id):
        with self.session_factory() as db:
            req = db.get(models.ConsultationRequest, request_id)
            if req is None or req.status != "queued":
                return
            req.status, req.started_at = "running", utcnow()
            db.commit()
            deadline = time.monotonic() + self.timeout

            def emit(stage):
                if time.monotonic() > deadline:
                    raise JobTimeout()
                req.stage = stage
                add_event(db, req.id, "stage", {"stage": stage})
                db.commit()

            try:
                user_message = db.get(models.Message, req.user_message_id)
                memories = [rm.snapshot for rm in db.scalars(select(models.RequestMemory).where(models.RequestMemory.request_id == req.id))
                            if rm.snapshot and not rm.deleted]
                result = self.engine.consult(user_message.content, history_before(db, user_message), memories,
                                             facts_for_ai(db, req.conversation_id), emit)
                if time.monotonic() > deadline:
                    raise JobTimeout()
                finished = utcnow()
                duration_ms = int((finished - req.created_at).total_seconds() * 1000)
                answer = models.Message(conversation_id=req.conversation_id, role="assistant", kind="answer",
                                        content=result["answer"], result=answer_record(self.engine, result, duration_ms))
                db.add(answer)
                db.flush()
                save_answer_items(db, req.conversation_id, answer.id, user_message.id, result.get("checklist", []))
                req.status, req.stage, req.finished_at, req.assistant_message_id = "succeeded", None, finished, answer.id
                db.get(models.Conversation, req.conversation_id).last_message_at = finished
                db.add(models.MetricEvent(type="request_succeeded", duration_ms=duration_ms, route=result["route"]))
                add_event(db, req.id, "done", {"message_id": str(answer.id)})
                db.commit()
            except Exception as exc:  # 작업 실패는 사용자에게 재시도 버튼으로 보여 줍니다.
                db.rollback()
                kind = error_type_of(exc)
                req = db.get(models.ConsultationRequest, request_id)
                finished = utcnow()
                req.status, req.error_type, req.finished_at = "failed", kind, finished
                add_event(db, req.id, "error", {"error_type": kind, "message": ERROR_MESSAGES[kind], "retryable": True})
                db.add(models.MetricEvent(type="request_failed", error_type=kind,
                                          duration_ms=int((finished - req.created_at).total_seconds() * 1000)))
                db.commit()
                if kind == "internal":
                    import traceback
                    traceback.print_exception(exc)
