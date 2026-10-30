# -*- coding: utf-8 -*-
"""/api 라우터 모음. 다른 사용자의 항목은 존재 여부를 숨기려고 모두 404로 응답합니다."""
import uuid

from fastapi import HTTPException


def parse_id(raw):
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        raise HTTPException(404, "찾을 수 없습니다.")


def owned(db, model, raw_id, user_id):
    """user_id가 소유한 항목만 돌려줍니다. 없거나 남의 것이면 404입니다."""
    row = db.get(model, parse_id(raw_id))
    if row is None or row.user_id != user_id:
        raise HTTPException(404, "찾을 수 없습니다.")
    return row


def iso(value):
    return value.isoformat() if value else None
