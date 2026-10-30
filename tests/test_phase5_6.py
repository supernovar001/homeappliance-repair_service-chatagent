# -*- coding: utf-8 -*-
"""5단계 기억(AT-04~06, AT-14), 6단계 북마크·관리자·보관 기간(AT-16, AT-17)."""
import uuid
from datetime import timedelta

from fastapi.testclient import TestClient

from backend import models
from backend.db import utcnow
from backend.retention import purge


def rid():
    return f"req-{uuid.uuid4()}"


def consult_once(client, product_of, wait_done, question="배수 호스 바로 놓았는데 그래도 OE가 떠요"):
    p = product_of(client)
    c = client.post("/api/conversations", json={"product_id": p["id"]}).json()
    r = client.post(f"/api/conversations/{c['id']}/messages", json={"content": question, "client_request_id": rid()}).json()
    wait_done(client, r["request"]["id"])
    return p, client.get(f"/api/conversations/{c['id']}").json()


def confirm_draft(client, conversation_id):
    drafts = client.post(f"/api/conversations/{conversation_id}/memory-drafts").json()
    d = drafts[0]
    return client.patch(f"/api/memories/{d['id']}", json={"symptom": d["symptom"], "action": d["action"], "outcome": d["outcome"], "confirm": True}).json()


def test_memory_draft_confirm_and_default_selection(login, product_of, wait_done):
    alice = login()
    p, c = consult_once(alice, product_of, wait_done)
    drafts = alice.post(f"/api/conversations/{c['id']}/memory-drafts").json()
    assert [d["status"] for d in drafts] == ["draft"] and drafts[0]["evidence"].startswith("배수 호스")
    again = alice.post(f"/api/conversations/{c['id']}/memory-drafts").json()  # 다시 만들면 이전 초안을 바꿉니다.
    assert len(alice.get(f"/api/products/{p['id']}/memories").json()) == 1 and again[0]["id"] != drafts[0]["id"]
    m = alice.patch(f"/api/memories/{again[0]['id']}", json={"symptom": "OE", "action": "호스 정리", "outcome": "해결되지 않음", "confirm": True}).json()
    assert m["status"] == "confirmed" and m["version"] == 1
    new = alice.post("/api/conversations", json={"product_id": p["id"]}).json()
    assert new["will_apply"] == [m["id"]]


def test_at05_editing_confirmed_memory_bumps_version_and_keeps_old_snapshot(login, product_of, wait_done, engine_fake):
    alice = login()
    p, c = consult_once(alice, product_of, wait_done)
    m = confirm_draft(alice, c["id"])
    new = alice.post("/api/conversations", json={"product_id": p["id"]}).json()
    r = alice.post(f"/api/conversations/{new['id']}/messages", json={"content": "OE 또 떠요", "client_request_id": rid()}).json()
    wait_done(alice, r["request"]["id"])
    edited = alice.patch(f"/api/memories/{m['id']}", json={"symptom": "OE", "action": "호스를 벽에서 떼어 놓음", "outcome": "해결됨"}).json()
    assert edited["version"] == 2
    applied = alice.get(f"/api/conversations/{new['id']}").json()["messages"][-1]["applied_memories"]
    assert applied[0]["version"] == 1 and applied[0]["action"] == m["action"]  # 지난 답변은 그때 내용 그대로


def test_at06_deleted_memory_is_scrubbed_from_past_answers(login, product_of, wait_done):
    alice = login()
    p, c = consult_once(alice, product_of, wait_done)
    m = confirm_draft(alice, c["id"])
    new = alice.post("/api/conversations", json={"product_id": p["id"]}).json()
    r = alice.post(f"/api/conversations/{new['id']}/messages", json={"content": "OE 또 떠요", "client_request_id": rid()}).json()
    wait_done(alice, r["request"]["id"])
    assert alice.delete(f"/api/memories/{m['id']}").status_code == 204
    detail = alice.get(f"/api/conversations/{new['id']}").json()
    assert detail["messages"][-1]["applied_memories"] == [{"memory_id": None, "version": 1, "deleted": True}]
    assert detail["memories"] == [] and detail["will_apply"] == []


def test_at04_memory_selection_only_same_product_confirmed(login, product_of, wait_done, engine_fake):
    alice, bob = login("alice@example.com"), login("bob@example.com")
    p, c = consult_once(alice, product_of, wait_done)
    m = confirm_draft(alice, c["id"])
    other = product_of(alice, "w1310n", "부모님댁")
    oc = alice.post("/api/conversations", json={"product_id": other["id"]}).json()
    assert alice.put(f"/api/conversations/{oc['id']}/memory-selection", json={"memory_ids": [m["id"]]}).status_code == 422
    bp = product_of(bob)
    bc = bob.post("/api/conversations", json={"product_id": bp["id"]}).json()
    assert bob.put(f"/api/conversations/{bc['id']}/memory-selection", json={"memory_ids": [m["id"]]}).status_code == 422
    assert bob.patch(f"/api/memories/{m['id']}", json={"symptom": "x", "action": "x", "outcome": "해결됨"}).status_code == 404
    # 선택을 빼면 작업 입력에서도 빠집니다.
    same = alice.post("/api/conversations", json={"product_id": p["id"]}).json()
    assert alice.put(f"/api/conversations/{same['id']}/memory-selection", json={"memory_ids": []}).json()["will_apply"] == []
    r = alice.post(f"/api/conversations/{same['id']}/messages", json={"content": "OE", "client_request_id": rid()}).json()
    wait_done(alice, r["request"]["id"])
    assert engine_fake.calls[-1]["memories"] == []


def test_at14_deleting_conversation_deletes_its_memories(login, product_of, wait_done, db):
    alice = login()
    p, c = consult_once(alice, product_of, wait_done)
    confirm_draft(alice, c["id"])
    assert alice.get(f"/api/conversations/{c['id']}").json()["source_memory_count"] == 1
    assert alice.delete(f"/api/conversations/{c['id']}").status_code == 204
    assert alice.get(f"/api/products/{p['id']}/memories").json() == []


def test_retention_keeps_confirmed_memory_and_unlinks_source(login, product_of, wait_done, db):
    alice = login()
    p, c = consult_once(alice, product_of, wait_done)
    m = confirm_draft(alice, c["id"])
    alice.post(f"/api/conversations/{c['id']}/memory-drafts")  # 확인하지 않은 초안 하나 더
    db.query(models.Conversation).filter_by(id=uuid.UUID(c["id"])).update({"last_message_at": utcnow() - timedelta(days=91)})
    db.commit()
    assert purge(db)["conversations"] == 1
    left = alice.get(f"/api/products/{p['id']}/memories").json()
    assert [(x["id"], x["status"], x["source_conversation_id"]) for x in left] == [(m["id"], "confirmed", None)]
    assert db.query(models.Message).count() == 0 and db.query(models.ConsultationRequest).count() == 0
    assert db.query(models.MetricEvent).filter_by(type="request_succeeded").count() == 1  # 통계는 남습니다.


def test_retention_keeps_recent_and_purges_expired_sessions(login, product_of, wait_done, db):
    alice = login()
    consult_once(alice, product_of, wait_done)
    db.query(models.Session).update({"expires_at": utcnow() - timedelta(seconds=1)})
    db.commit()
    assert purge(db) == {"conversations": 0, "sessions": 1}


def test_at16_bookmarks(login, product_of, wait_done):
    alice, bob = login("alice@example.com"), login("bob@example.com")
    p, c = consult_once(alice, product_of, wait_done)
    answer, question = c["messages"][-1], c["messages"][0]
    assert alice.put(f"/api/messages/{question['id']}/bookmark").status_code == 422
    assert bob.put(f"/api/messages/{answer['id']}/bookmark").status_code == 404
    assert alice.put(f"/api/messages/{answer['id']}/bookmark").status_code == 204
    assert alice.put(f"/api/messages/{answer['id']}/bookmark").status_code == 204  # 두 번 눌러도 하나
    page = alice.get("/api/bookmarks", params={"q": "배수"}).json()
    assert page["total"] == 1 and page["items"][0]["question"] == question["content"] and page["items"][0]["checklist_count"] == 2
    assert alice.get("/api/bookmarks", params={"product_id": p["id"]}).json()["total"] == 1
    assert alice.get(f"/api/conversations/{c['id']}").json()["messages"][-1]["bookmarked"] is True
    assert bob.get("/api/bookmarks").json()["total"] == 0
    assert alice.delete(f"/api/messages/{answer['id']}/bookmark").status_code == 204
    assert alice.get("/api/bookmarks").json()["total"] == 0


def test_at17_admin_only_and_audited(login, product_of, wait_done, db, app):
    alice, admin = login("alice@example.com"), login("admin@example.com")
    _, c = consult_once(alice, product_of, wait_done)
    for url in ("/api/admin/stats", "/api/admin/conversations", f"/api/admin/conversations/{c['id']}"):
        assert alice.get(url).status_code == 403
    assert TestClient(app).get("/api/admin/stats").status_code == 401
    stats = admin.get("/api/admin/stats").json()
    assert stats["has_data"] and stats["current"]["conversations"] == 1 and stats["current"]["answers"] == 1
    assert stats["daily_answers"][-1]["count"] == 1 and len(stats["daily_answers"]) == 7
    assert {r["route"]: r["count"] for r in stats["routes"]}["자가 점검 우선"] == 1
    listed = admin.get("/api/admin/conversations").json()["items"][0]
    assert listed["user"] == "al***@example.com" and listed["last_route"] == "자가 점검 우선"
    detail = admin.get(f"/api/admin/conversations/{c['id']}").json()
    assert detail["messages"][0]["content"].startswith("배수 호스") and detail["requests"][0]["status"] == "succeeded"
    log = db.query(models.AdminAuditLog).one()
    assert log.action == "view_conversation" and log.target_id == c["id"]


def test_admin_stats_without_data(login):
    stats = login("admin@example.com").get("/api/admin/stats").json()
    assert stats["has_data"] is False and stats["current"]["median_ms"] is None


def test_page_highlight_uses_answer_evidence(login, product_of, wait_done, engine_fake):
    alice, bob = login("alice@example.com"), login("bob@example.com")
    _, c = consult_once(alice, product_of, wait_done)
    answer = c["messages"][-1]
    assert alice.get(f"/api/manuals/MFL71831423/pages/41?message_id={answer['id']}").status_code == 200
    assert engine_fake.calls[-1] == {"page": 41, "highlights": ["배수 호스가 꺾이지 않았는지 확인하세요."]}
    assert bob.get(f"/api/manuals/MFL71831423/pages/41?message_id={answer['id']}").status_code == 404
