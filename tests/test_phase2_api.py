# -*- coding: utf-8 -*-
"""2단계: 로그인·세션·CSRF·제품·상담 API (AT-02, AT-03, AT-07, AT-15)."""
import importlib.util
import re
import uuid
from datetime import timedelta

from fastapi.testclient import TestClient

from backend import models
from backend.api.products import pattern_regex
from backend.db import utcnow


def test_seed_pages_match_app_washer_pages():
    # app.py를 불러오면 모델을 읽어 느리므로, 정의 줄만 읽어 마이그레이션 값과 비교합니다.
    source = open("app.py", encoding="utf-8").read()
    expr = re.search(r"^WASHER_PAGES = (.+)$", source, re.M).group(1)
    app_pages = eval(expr, {"__builtins__": {}}, {"list": list, "range": range})
    spec = importlib.util.spec_from_file_location("m0001", "migrations/versions/0001_initial.py")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.WASHER_PAGES == app_pages and len(app_pages) == 40


def test_unauthenticated_requests_are_rejected(app):
    client = TestClient(app)
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/products").status_code == 401
    assert client.get("/api/conversations").status_code == 401


def test_expired_session_is_rejected(login, db):
    alice = login()
    db.query(models.Session).filter_by(user_id=alice.user.id).update({"expires_at": utcnow() - timedelta(minutes=1)})
    db.commit()
    assert alice.get("/api/me").status_code == 401


def test_session_token_is_stored_hashed(login, db):
    alice = login()
    token = alice.client.cookies.get("wc_session")
    stored = db.query(models.Session).filter_by(user_id=alice.user.id).one()
    assert stored.token_hash != token and len(stored.token_hash) == 64


def test_me_reports_admin_from_env(login):
    assert login().get("/api/me").json()["is_admin"] is False
    me = login("Admin@example.com").get("/api/me").json()
    assert me["is_admin"] is True and me["csrf_token"]


def test_writes_require_csrf_token_and_allowed_origin(login):
    alice = login()
    body = {"supported_model_id": "w10n", "nickname": "집"}
    assert alice.post("/api/products", json=body, csrf=False).status_code == 403
    assert alice.post("/api/products", json=body, headers={"X-CSRF-Token": "wrong"}, csrf=False).status_code == 403
    assert alice.post("/api/products", json=body, headers={"Origin": "https://evil.example"}).status_code == 403
    assert alice.post("/api/products", json=body, headers={"Origin": "http://testserver"}).status_code == 201


def test_logout_deletes_session(login):
    alice = login()
    assert alice.post("/auth/logout").status_code == 204
    alice.client.cookies.set("wc_session", "gone")
    assert alice.get("/api/me").status_code == 401


def test_supported_models_are_the_two_manual_series(login):
    series = [m["series"] for m in login().get("/api/supported-models").json()]
    assert series == ["W10**N", "W1310**N"]


def test_model_code_pattern():
    assert pattern_regex("F13*J(*)N").fullmatch("F13AJN") and pattern_regex("F13*J(*)N").fullmatch("F13AJBN")
    assert not pattern_regex("F13*J(*)N").fullmatch("F13AJBNR")
    assert pattern_regex("W1310**N").fullmatch("W1310ABN") and not pattern_regex("W10**N").fullmatch("W1310ABN")


def test_at02_product_register_and_rename(login, product_of):
    alice = login()
    p = product_of(alice)
    assert p["supported_model"]["series"] == "W10**N" and p["memory_count"] == 0
    r = alice.post("/api/products", json={"supported_model_id": "w1310n", "nickname": "부모님댁", "model_code": "w1310 abn"})
    assert r.status_code == 201 and r.json()["model_code"] == "W1310ABN"
    bad = alice.post("/api/products", json={"supported_model_id": "w10n", "nickname": "x", "model_code": "W1310ABN"})
    assert bad.status_code == 422
    assert alice.post("/api/products", json={"supported_model_id": "fridge", "nickname": "x"}).status_code == 422
    assert alice.patch(f"/api/products/{p['id']}", json={"nickname": "  거실  "}).json()["nickname"] == "거실"
    assert [x["nickname"] for x in alice.get("/api/products").json()] == ["거실", "부모님댁"]


def test_at03_conversation_create_list_rename_delete(login, product_of):
    alice = login()
    p = product_of(alice)
    c = alice.post("/api/conversations", json={"product_id": p["id"]}).json()
    assert c["title"] == "새 상담" and c["messages"] == [] and c["request"] is None
    assert alice.patch(f"/api/conversations/{c['id']}", json={"title": "OE 문의"}).json()["title"] == "OE 문의"
    listed = alice.get("/api/conversations", params={"q": "OE"}).json()
    assert listed["total"] == 1 and listed["items"][0]["product_nickname"] == "우리집 워시타워"
    assert alice.get("/api/conversations", params={"q": "없는말"}).json()["total"] == 0
    assert alice.delete(f"/api/conversations/{c['id']}").status_code == 204
    assert alice.get(f"/api/conversations/{c['id']}").status_code == 404


def test_at07_product_change_blocked_after_first_message(login, product_of, db):
    alice = login()
    p1, p2 = product_of(alice), product_of(alice, "w1310n", "부모님댁")
    c = alice.post("/api/conversations", json={"product_id": p1["id"]}).json()
    assert alice.patch(f"/api/conversations/{c['id']}", json={"product_id": p2["id"]}).json()["product_id"] == p2["id"]
    db.add(models.Message(conversation_id=uuid.UUID(c["id"]), role="user", kind="question", content="OE가 떠요"))
    db.commit()
    assert alice.patch(f"/api/conversations/{c['id']}", json={"product_id": p1["id"]}).status_code == 409


def test_new_conversation_selects_confirmed_memories(login, product_of, db):
    alice = login()
    p = product_of(alice)
    pid = uuid.UUID(p["id"])
    confirmed = models.Memory(user_id=alice.user.id, product_id=pid, symptom="OE", action="호스 정리", outcome="해결됨", status="confirmed")
    draft = models.Memory(user_id=alice.user.id, product_id=pid, symptom="UE", action="이불 분리", outcome="해결됨", status="draft")
    db.add_all([confirmed, draft])
    db.commit()
    c = alice.post("/api/conversations", json={"product_id": p["id"]}).json()
    assert c["will_apply"] == [str(confirmed.id)] and [m["selected"] for m in c["memories"]] == [True]


def test_at15_other_users_items_are_404(login, product_of):
    alice, bob = login("alice@example.com"), login("bob@example.com")
    p = product_of(alice)
    c = alice.post("/api/conversations", json={"product_id": p["id"]}).json()
    assert bob.get(f"/api/conversations/{c['id']}").status_code == 404
    assert bob.patch(f"/api/conversations/{c['id']}", json={"title": "x"}).status_code == 404
    assert bob.delete(f"/api/conversations/{c['id']}").status_code == 404
    assert bob.patch(f"/api/products/{p['id']}", json={"nickname": "x"}).status_code == 404
    assert bob.post("/api/conversations", json={"product_id": p["id"]}).status_code == 404
    assert bob.get("/api/conversations/not-a-uuid").status_code == 404
    assert bob.get("/api/conversations").json()["total"] == 0 and bob.get("/api/products").json() == []


def _fake_google(monkeypatch, userinfo):
    from backend import auth

    async def fake_token(request):
        return {"userinfo": userinfo}
    monkeypatch.setattr(auth.oauth.google, "authorize_access_token", fake_token)


def test_google_callback_creates_session_for_verified_email(app, monkeypatch, db):
    _fake_google(monkeypatch, {"sub": "g-1", "email": "New@Example.com", "email_verified": True, "name": "새 사용자"})
    client = TestClient(app)
    r = client.get("/auth/google/callback", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    cookie = r.headers["set-cookie"]
    assert "wc_session=" in cookie and "HttpOnly" in cookie and "samesite=lax" in cookie.lower()
    assert client.get("/api/me").json()["email"] == "new@example.com"


def test_google_callback_rejects_unverified_email(app, monkeypatch, db):
    _fake_google(monkeypatch, {"sub": "g-2", "email": "x@example.com", "email_verified": False})
    r = TestClient(app).get("/auth/google/callback", follow_redirects=False)
    assert r.headers["location"] == "/?login_error=unverified" and "wc_session" not in r.headers.get("set-cookie", "")
    assert db.query(models.User).count() == 0
