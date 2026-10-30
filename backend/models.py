# -*- coding: utf-8 -*-
"""DB 테이블. 키는 UUID, 시간은 UTC(timestamptz)로 저장합니다.

상담을 지우면(사용자 삭제·90일 보관 기간) 메시지·작업·이벤트·체크리스트·북마크가 함께 지워집니다.
확인된 기억은 남기고 출처 상담 연결(source_conversation_id)만 끊습니다.
"""
import uuid
from datetime import datetime

from sqlalchemy import (JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .db import utcnow

Json = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


def _id():
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def _created():
    return mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _id()
    google_sub: Mapped[str] = mapped_column(String(255), unique=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    picture: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _created()
    last_login_at: Mapped[datetime] = _created()


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[uuid.UUID] = _id()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)  # 쿠키 토큰의 sha256. 토큰 원문은 저장하지 않습니다.
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Manual(Base):
    __tablename__ = "manuals"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # 예: MFL71831423
    title: Mapped[str] = mapped_column(String(200))
    revision: Mapped[str] = mapped_column(String(20))
    file_name: Mapped[str] = mapped_column(String(200))
    allowed_pages: Mapped[list] = mapped_column(Json)  # 상담에서 인용·표시할 수 있는 세탁기 페이지


class SupportedModel(Base):
    __tablename__ = "supported_models"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # 예: w10n
    series: Mapped[str] = mapped_column(String(40))                # 설명서 표기: W10**N
    washer_model: Mapped[str] = mapped_column(String(40))          # F13*J(*)N
    dryer_model: Mapped[str] = mapped_column(String(40))           # RH10*J(*)N
    manual_id: Mapped[str] = mapped_column(ForeignKey("manuals.id"))
    position: Mapped[int] = mapped_column(Integer, default=0)


class Product(Base):
    __tablename__ = "products"
    id: Mapped[uuid.UUID] = _id()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    supported_model_id: Mapped[str] = mapped_column(ForeignKey("supported_models.id"))
    nickname: Mapped[str] = mapped_column(String(40))
    model_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = _created()


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[uuid.UUID] = _id()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), index=True)
    title: Mapped[str] = mapped_column(String(100), default="새 상담")
    created_at: Mapped[datetime] = _created()
    last_message_at: Mapped[datetime] = _created()  # 보관 기간의 기준(마지막 대화 시각)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[uuid.UUID] = _id()
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))   # user | assistant
    kind: Mapped[str] = mapped_column(String(30))   # question | checklist_report | answer
    content: Mapped[str] = mapped_column(Text)
    result: Mapped[dict | None] = mapped_column(Json, nullable=True)  # 답변의 판단·근거 페이지·처리 정보
    created_at: Mapped[datetime] = _created()


class ConsultationRequest(Base):
    __tablename__ = "consultation_requests"
    __table_args__ = (UniqueConstraint("user_id", "client_request_id"),)
    id: Mapped[uuid.UUID] = _id()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    client_request_id: Mapped[str] = mapped_column(String(64))
    user_message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"))
    assistant_message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued | running | succeeded | failed | interrupted
    stage: Mapped[str | None] = mapped_column(String(30), nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = _created()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RequestEvent(Base):
    __tablename__ = "request_events"
    __table_args__ = (UniqueConstraint("request_id", "seq"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("consultation_requests.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)          # SSE 이벤트 ID(Last-Event-ID)
    type: Mapped[str] = mapped_column(String(20))      # stage | done | error
    data: Mapped[dict] = mapped_column(Json, default=dict)
    created_at: Mapped[datetime] = _created()


class ChecklistItem(Base):
    __tablename__ = "checklist_items"
    id: Mapped[uuid.UUID] = _id()
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)  # 항목을 만든 답변
    key: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str] = mapped_column(Text, default="")
    pages: Mapped[list] = mapped_column(Json, default=list)
    kind: Mapped[str] = mapped_column(String(20))       # self_check | contact_service
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default="미확인")
    outcome: Mapped[str] = mapped_column(String(20), default="결과 불명")
    inherited_from_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("checklist_items.id", ondelete="SET NULL"), nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _created()


class ChecklistEvent(Base):
    __tablename__ = "checklist_events"
    id: Mapped[uuid.UUID] = _id()
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("checklist_items.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), nullable=True)  # 결과를 알린 고객 발화
    status: Mapped[str] = mapped_column(String(20))
    outcome: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(20))     # button | free_text
    evidence: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _created()


class Memory(Base):
    __tablename__ = "memories"
    id: Mapped[uuid.UUID] = _id()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    source_conversation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True)
    symptom: Mapped[str] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(300))
    outcome: Mapped[str] = mapped_column(String(20))    # 해결됨 | 해결되지 않음 | 결과 미확인
    evidence: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | confirmed
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = _created()
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = _created()


class ConversationMemory(Base):
    """상담에 적용하도록 선택된 기억(새 상담을 만들 때 확인된 기억이 모두 선택됩니다)."""
    __tablename__ = "conversation_memories"
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True)
    memory_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("memories.id", ondelete="CASCADE"), primary_key=True)


class RequestMemory(Base):
    """작업 시작 시점에 실제로 AI에 넣은 기억의 스냅샷입니다. 기억을 지우면 스냅샷을 비우고 deleted로 표시합니다."""
    __tablename__ = "request_memories"
    id: Mapped[uuid.UUID] = _id()
    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("consultation_requests.id", ondelete="CASCADE"), index=True)
    memory_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("memories.id", ondelete="SET NULL"), nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict | None] = mapped_column(Json, nullable=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class Bookmark(Base):
    __tablename__ = "bookmarks"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = _created()


class MetricEvent(Base):
    """관리자 통계용 기록. 개인정보가 없어 상담이 지워져도 남습니다."""
    __tablename__ = "metric_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(30), index=True)  # conversation_created | request_succeeded | request_failed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    route: Mapped[str | None] = mapped_column(String(30), nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(40), nullable=True)


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    admin_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = _created()
