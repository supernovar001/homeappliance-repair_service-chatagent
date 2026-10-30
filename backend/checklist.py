# -*- coding: utf-8 -*-
"""점검 체크리스트 저장과 상태 승계.

새 답변의 항목은 같은 상담의 이전 항목과 key가 같거나 제목이 비슷하면(유사도 0.8 이상) 상태·결과를 이어받습니다.
고객이 자유 입력으로 알린 결과는 app.py가 근거 발화를 확인한 경우에만 반영하고 checklist_events에 남깁니다.
"""
import re
from difflib import SequenceMatcher

from sqlalchemy import select

from . import models

CHECK_STATUSES = ["미확인", "확인 완료", "수행 어려움", "해당 없음"]
CHECK_OUTCOMES = ["결과 불명", "이상 없음", "이상 발견", "해결됨", "해결되지 않음"]
TITLE_SIMILARITY = 0.8


def _title_key(title):
    return re.sub(r"[\s·,./()\-]+", "", title)


def similar(a, b):
    return SequenceMatcher(None, _title_key(a), _title_key(b)).ratio() >= TITLE_SIMILARITY


def latest_items(db, conversation_id):
    """key별로 가장 최근 항목만 돌려줍니다(지금 상담의 점검 현황)."""
    items = db.scalars(select(models.ChecklistItem).where(models.ChecklistItem.conversation_id == conversation_id)
                       .order_by(models.ChecklistItem.created_at, models.ChecklistItem.position))
    latest = {}
    for item in items:
        latest[item.key] = item
    return list(latest.values())


def current_answer_items(db, conversation_id):
    """가장 최근 답변이 만든 항목(점검 결과를 알릴 수 있는 항목)."""
    message_id = db.scalar(select(models.ChecklistItem.message_id).where(models.ChecklistItem.conversation_id == conversation_id)
                           .order_by(models.ChecklistItem.created_at.desc()).limit(1))
    if message_id is None:
        return []
    return list(db.scalars(select(models.ChecklistItem).where(models.ChecklistItem.message_id == message_id)
                           .order_by(models.ChecklistItem.position)))


def facts_for_ai(db, conversation_id):
    return [{"key": i.key, "title": i.title, "status": i.status, "outcome": i.outcome} for i in latest_items(db, conversation_id)]


def save_answer_items(db, conversation_id, answer_message_id, user_message_id, items):
    previous = latest_items(db, conversation_id)
    saved = []
    for position, item in enumerate(items):
        prev = next((p for p in previous if p.key == item["key"]), None) or next((p for p in previous if similar(p.title, item["title"])), None)
        row = models.ChecklistItem(
            conversation_id=conversation_id, message_id=answer_message_id, key=item["key"], title=item["title"],
            detail=item.get("detail", ""), pages=item["pages"], kind=item["kind"], enabled=item.get("enabled", True), position=position,
            status=prev.status if prev else "미확인", outcome=prev.outcome if prev else "결과 불명",
            inherited_from_item_id=prev.id if prev else None)
        if prev and prev.key != item["key"]:
            row.key = prev.key  # 제목으로 이어받은 항목은 이전 key를 써서 다음 답변에서도 같은 항목으로 봅니다.
        db.add(row)
        db.flush()
        report, outcome = item.get("customer_report", "미확인"), item.get("customer_outcome", "결과 불명")
        if item.get("evidence") and report in CHECK_STATUSES and report != "미확인" and outcome in CHECK_OUTCOMES:
            row.status, row.outcome = report, outcome
            db.add(models.ChecklistEvent(item_id=row.id, message_id=user_message_id, status=report, outcome=outcome,
                                         source="free_text", evidence=item["evidence"]))
        saved.append(row)
    return saved


def report_text(rows, note=""):
    """버튼으로 알린 점검 결과를 대화에 남길 고객 발화로 만듭니다."""
    lines = ["[점검 결과]"] + [f"- {item.title}: {status}, {outcome}" for item, status, outcome in rows]
    if note.strip():
        lines.append(note.strip())
    return "\n".join(lines)
