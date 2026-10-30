# -*- coding: utf-8 -*-
"""내 정보·지원 모델·제품 API."""
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from .. import models
from ..auth import Viewer, current_viewer
from ..db import get_db
from . import iso, owned

router = APIRouter(prefix="/api")


def pattern_regex(pattern):
    """설명서 표기를 정규식으로 바꿉니다. '*'는 영숫자 1자, '(*)'는 영숫자 0~1자입니다. 예: F13*J(*)N → F13[A-Z0-9]J[A-Z0-9]?N"""
    parts = re.split(r"(\(\*\)|\*)", pattern)
    body = "".join("[A-Z0-9]?" if p == "(*)" else "[A-Z0-9]" if p == "*" else re.escape(p) for p in parts)
    return re.compile(body)


def model_code_matches(model, code):
    """제품 라벨의 모델명이 시리즈 표기, 세탁기 모델, 건조기 모델 중 하나와 맞는지 봅니다."""
    return any(pattern_regex(p).fullmatch(code) for p in (model.series, model.washer_model, model.dryer_model))


def supported_model_json(m):
    return {"id": m.id, "series": m.series, "washer_model": m.washer_model, "dryer_model": m.dryer_model, "manual_id": m.manual_id}


def product_json(db, p, model=None):
    model = model or db.get(models.SupportedModel, p.supported_model_id)
    counts = dict(db.execute(select(models.Memory.status, func.count()).where(models.Memory.product_id == p.id)
                             .group_by(models.Memory.status)).all())
    conversations = db.scalar(select(func.count()).select_from(models.Conversation).where(models.Conversation.product_id == p.id))
    return {"id": str(p.id), "nickname": p.nickname, "model_code": p.model_code, "created_at": iso(p.created_at),
            "supported_model": supported_model_json(model), "conversation_count": conversations,
            "memory_count": counts.get("confirmed", 0), "draft_memory_count": counts.get("draft", 0)}


@router.get("/me")
def me(viewer: Viewer = Depends(current_viewer)):
    u = viewer.user
    return {"id": str(u.id), "email": u.email, "name": u.name, "picture": u.picture,
            "is_admin": viewer.is_admin, "csrf_token": viewer.session.csrf_token}


@router.get("/supported-models")
def supported_models(viewer: Viewer = Depends(current_viewer), db: DbSession = Depends(get_db)):
    return [supported_model_json(m) for m in db.scalars(select(models.SupportedModel).order_by(models.SupportedModel.position))]


class ProductIn(BaseModel):
    supported_model_id: str
    nickname: str = Field(min_length=1, max_length=40)
    model_code: str | None = Field(default=None, max_length=40)


class ProductPatch(BaseModel):
    nickname: str = Field(min_length=1, max_length=40)


@router.get("/products")
def list_products(viewer: Viewer = Depends(current_viewer), db: DbSession = Depends(get_db)):
    rows = db.scalars(select(models.Product).where(models.Product.user_id == viewer.user.id).order_by(models.Product.created_at))
    return [product_json(db, p) for p in rows]


@router.post("/products", status_code=201)
def create_product(body: ProductIn, viewer: Viewer = Depends(current_viewer), db: DbSession = Depends(get_db)):
    model = db.get(models.SupportedModel, body.supported_model_id)
    if model is None:
        raise HTTPException(422, "지원하지 않는 모델 시리즈입니다.")
    nickname = body.nickname.strip()
    if not nickname:
        raise HTTPException(422, "별명을 입력해 주세요.")
    code = re.sub(r"\s+", "", body.model_code or "").upper() or None
    if code and not model_code_matches(model, code):
        raise HTTPException(422, f"모델명이 {model.series} 시리즈 형식과 맞지 않습니다.")
    product = models.Product(user_id=viewer.user.id, supported_model_id=model.id, nickname=nickname, model_code=code)
    db.add(product)
    db.commit()
    return product_json(db, product, model)


@router.patch("/products/{product_id}")
def update_product(product_id: str, body: ProductPatch, viewer: Viewer = Depends(current_viewer), db: DbSession = Depends(get_db)):
    product = owned(db, models.Product, product_id, viewer.user.id)
    nickname = body.nickname.strip()
    if not nickname:
        raise HTTPException(422, "별명을 입력해 주세요.")
    product.nickname = nickname
    db.commit()
    return product_json(db, product)
