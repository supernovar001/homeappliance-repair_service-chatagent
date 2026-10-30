# -*- coding: utf-8 -*-
"""3단계: 상담 작업·SSE·재시도·체크리스트 승계·근거 페이지 (AT-08~AT-13)."""
import uuid

from fastapi.testclient import TestClient

from backend import models
from backend.engine import FakeEngine
from backend.jobs import JobRunner


def rid():
    return f"req-{uuid.uuid4()}"


def start(client, product_of):
    p = product_of(client)
    return client.post("/api/conversations", json={"product_id": p["id"]}).json()


def ask(client, conversation_id, content, request_id=None):
    return client.post(f"/api/conversations/{conversation_id}/messages", json={"content": content, "client_request_id": request_id or rid()})


def sse(client, request_id, **headers):
    with client.client.stream("GET", f"/api/requests/{request_id}/events", headers=headers) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        events, current = [], {}
        for line in r.iter_lines():
            if line.startswith("id: "):
                current["id"] = int(line[4:])
            elif line.startswith("event: "):
                current["event"] = line[7:]
            elif line == "" and current:
                events.append(current)
                current = {}
        return events


def test_at08_question_runs_in_background_and_streams_stages(login, product_of, wait_done):
    alice = login()
    c = start(alice, product_of)
    r = ask(alice, c["id"], "OE가 떠요. 물이 안 빠져요.")
    assert r.status_code == 202 and r.json()["request"]["status"] == "queued"
    req_id = r.json()["request"]["id"]
    events = sse(alice, req_id)
    assert [e["event"] for e in events] == ["stage"] * 4 + ["done"] and [e["id"] for e in events] == [1, 2, 3, 4, 5]
    assert wait_done(alice, req_id)["status"] == "succeeded"
    detail = alice.get(f"/api/conversations/{c['id']}").json()
    assert detail["title"] == "OE가 떠요. 물이 안 빠져요."
    answer = detail["messages"][-1]
    assert answer["kind"] == "answer" and answer["result"]["route"] == "자가 점검 우선"
    assert answer["result"]["error_code"] == "OE" and answer["result"]["evidence_pages"] == [41]
    assert [i["key"] for i in detail["checklist"]] == ["drain_hose", "pump_filter"]


def test_sse_resumes_after_last_event_id(login, product_of, wait_done):
    alice = login()
    c = start(alice, product_of)
    req_id = ask(alice, c["id"], "OE가 떠요").json()["request"]["id"]
    wait_done(alice, req_id)
    assert [e["id"] for e in sse(alice, req_id, **{"Last-Event-ID": "3"})] == [4, 5]


def test_same_client_request_id_returns_same_job(login, product_of, wait_done, db):
    alice = login()
    c = start(alice, product_of)
    first = ask(alice, c["id"], "OE가 떠요", "req-dup-0001").json()
    again = ask(alice, c["id"], "OE가 떠요", "req-dup-0001").json()
    assert first["request"]["id"] == again["request"]["id"]
    wait_done(alice, first["request"]["id"])
    assert db.query(models.ConsultationRequest).count() == 1 and db.query(models.Message).filter_by(role="user").count() == 1


def test_at11_second_question_blocked_while_running(login, product_of, engine_fake, wait_done):
    alice = login()
    c = start(alice, product_of)
    engine_fake.gate.clear()
    req_id = ask(alice, c["id"], "SLOW OE가 떠요").json()["request"]["id"]
    assert ask(alice, c["id"], "하나 더요").status_code == 409
    assert alice.delete(f"/api/conversations/{c['id']}").status_code == 409
    engine_fake.gate.set()
    assert wait_done(alice, req_id)["status"] == "succeeded"
    assert ask(alice, c["id"], "하나 더요").status_code == 202


def test_question_length_and_rate_limit(login, product_of, db):
    alice = login()
    c = start(alice, product_of)
    assert ask(alice, c["id"], "가" * 2001).status_code == 422
    assert ask(alice, c["id"], "   ").status_code == 422
    msg = models.Message(conversation_id=uuid.UUID(c["id"]), role="user", kind="question", content="x")
    db.add(msg)
    db.flush()
    for i in range(20):
        db.add(models.ConsultationRequest(user_id=alice.user.id, conversation_id=msg.conversation_id, client_request_id=f"old-{i:04d}",
                                          user_message_id=msg.id, status="succeeded"))
    db.commit()
    assert ask(alice, c["id"], "OE가 떠요").status_code == 429


def test_at09_failed_job_can_be_retried(login, product_of, wait_done):
    alice = login()
    c = start(alice, product_of)
    req_id = ask(alice, c["id"], "FAIL OE가 떠요").json()["request"]["id"]
    events = sse(alice, req_id)
    assert events[-1]["event"] == "error"
    failed = wait_done(alice, req_id)
    assert failed["status"] == "failed" and failed["error_type"] == "internal"
    assert alice.post(f"/api/requests/{req_id}/retry").status_code == 202  # 엔진은 같은 발화로 다시 실패합니다.
    again = alice.get(f"/api/conversations/{c['id']}").json()["request"]
    assert again["attempt"] == 2 and again["user_message_id"] == failed["user_message_id"]
    wait_done(alice, again["id"])
    assert alice.post(f"/api/requests/{req_id}/retry").status_code == 409  # 가장 최근 작업만 재시도


def test_retry_rejects_succeeded_job(login, product_of, wait_done):
    alice = login()
    c = start(alice, product_of)
    req_id = ask(alice, c["id"], "OE가 떠요").json()["request"]["id"]
    wait_done(alice, req_id)
    assert alice.post(f"/api/requests/{req_id}/retry").status_code == 409


def test_job_timeout_marks_failed(login, product_of, db):
    alice = login()
    c = start(alice, product_of)
    cid = uuid.UUID(c["id"])
    msg = models.Message(conversation_id=cid, role="user", kind="question", content="OE")
    db.add(msg)
    db.flush()
    req = models.ConsultationRequest(user_id=alice.user.id, conversation_id=cid, client_request_id="req-timeout", user_message_id=msg.id)
    db.add(req)
    db.commit()
    JobRunner(FakeEngine(), 1, timeout_seconds=-1).run(req.id)
    db.refresh(req)
    assert req.status == "failed" and req.error_type == "timeout"


def test_recover_marks_unfinished_jobs_interrupted(login, product_of, db, app):
    alice = login()
    c = start(alice, product_of)
    cid = uuid.UUID(c["id"])
    msg = models.Message(conversation_id=cid, role="user", kind="question", content="OE")
    db.add(msg)
    db.flush()
    req = models.ConsultationRequest(user_id=alice.user.id, conversation_id=cid, client_request_id="req-crash", user_message_id=msg.id, status="running")
    db.add(req)
    db.commit()
    app.state.jobs.recover()
    db.refresh(req)
    assert req.status == "interrupted"
    assert sse(alice, str(req.id))[-1]["event"] == "error"
    assert alice.post(f"/api/requests/{req.id}/retry").status_code == 202


def test_at10_checklist_results_batch_and_inheritance(login, product_of, wait_done, engine_fake, db):
    alice = login()
    c = start(alice, product_of)
    wait_done(alice, ask(alice, c["id"], "OE가 떠요").json()["request"]["id"])
    items = {i["key"]: i for i in alice.get(f"/api/conversations/{c['id']}").json()["checklist"]}
    body = {"client_request_id": rid(), "note": "물은 조금 빠졌어요",
            "results": [{"item_id": items["drain_hose"]["id"], "status": "확인 완료", "outcome": "해결되지 않음"},
                        {"item_id": items["pump_filter"]["id"], "status": "수행 어려움", "outcome": "결과 불명"}]}
    r = alice.post(f"/api/conversations/{c['id']}/checklist-results", json=body)
    assert r.status_code == 202
    assert r.json()["user_message"]["content"].startswith("[점검 결과]\n- 배수 호스 꺾임·높이 확인: 확인 완료, 해결되지 않음")
    wait_done(alice, r.json()["request"]["id"])
    # 후속 답변 작업에는 점검 현황이 들어가고, 새 답변의 같은 항목은 상태를 이어받습니다.
    assert {f["key"]: f["status"] for f in engine_fake.calls[-1]["checklist"]} == {"drain_hose": "확인 완료", "pump_filter": "수행 어려움"}
    detail = alice.get(f"/api/conversations/{c['id']}").json()
    latest = [i for i in detail["checklist"] if i["message_id"] == detail["messages"][-1]["id"]]
    assert [(i["key"], i["status"], i["outcome"], i["inherited"]) for i in latest] == [
        ("drain_hose", "확인 완료", "해결되지 않음", True), ("pump_filter", "수행 어려움", "결과 불명", True)]
    assert db.query(models.ChecklistEvent).filter_by(source="button").count() == 2
    old = {"client_request_id": rid(), "results": [{"item_id": items["drain_hose"]["id"], "status": "확인 완료", "outcome": "해결됨"}]}
    assert alice.post(f"/api/conversations/{c['id']}/checklist-results", json=old).status_code == 422  # 지난 답변의 항목
    bad = {"client_request_id": rid(), "results": [{"item_id": latest[0]["id"], "status": "완료", "outcome": "해결됨"}]}
    assert alice.post(f"/api/conversations/{c['id']}/checklist-results", json=bad).status_code == 422


def test_free_text_report_updates_item_with_evidence(login, product_of, wait_done, db):
    alice = login()
    c = start(alice, product_of)
    wait_done(alice, ask(alice, c["id"], "OE가 떠요").json()["request"]["id"])
    wait_done(alice, ask(alice, c["id"], "호스 펴 놨는데 그래도 OE가 떠요").json()["request"]["id"])
    detail = alice.get(f"/api/conversations/{c['id']}").json()
    hose = [i for i in detail["checklist"] if i["key"] == "drain_hose"][-1]
    assert (hose["status"], hose["outcome"]) == ("확인 완료", "해결되지 않음")
    event = db.query(models.ChecklistEvent).filter_by(source="free_text").one()
    assert event.evidence == "호스 펴 놨는데 그래도 OE가 떠요"


def test_selected_memories_are_snapshotted_into_job(login, product_of, wait_done, engine_fake, db):
    alice = login()
    p = product_of(alice)
    db.add(models.Memory(user_id=alice.user.id, product_id=uuid.UUID(p["id"]), symptom="OE", action="호스 정리", outcome="해결됨", status="confirmed"))
    db.commit()
    c = alice.post("/api/conversations", json={"product_id": p["id"]}).json()
    wait_done(alice, ask(alice, c["id"], "OE가 또 떠요").json()["request"]["id"])
    assert engine_fake.calls[-1]["memories"] == [{"symptom": "OE", "action": "호스 정리", "outcome": "해결됨"}]
    applied = alice.get(f"/api/conversations/{c['id']}").json()["messages"][-1]["applied_memories"]
    assert [(m["action"], m["version"], m["deleted"]) for m in applied] == [("호스 정리", 1, False)]


def test_at12_manual_pages_only_allowed_and_logged_in(login, app):
    alice = login()
    r = alice.get("/api/manuals/MFL71831423/pages/41")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert alice.get("/api/manuals/MFL71831423/pages/10").status_code == 404
    assert alice.get("/api/manuals/OTHER/pages/41").status_code == 404
    assert TestClient(app).get("/api/manuals/MFL71831423/pages/41").status_code == 401


def test_at13_requests_of_other_users_are_404(login, product_of, wait_done):
    alice, bob = login("alice@example.com"), login("bob@example.com")
    c = start(alice, product_of)
    req_id = ask(alice, c["id"], "OE가 떠요").json()["request"]["id"]
    wait_done(alice, req_id)
    assert bob.get(f"/api/requests/{req_id}").status_code == 404
    assert bob.get(f"/api/requests/{req_id}/events").status_code == 404
    assert bob.post(f"/api/requests/{req_id}/retry").status_code == 404
    assert ask(bob, c["id"], "OE").status_code == 404


def test_healthz_and_examples(login, app):
    assert TestClient(app).get("/healthz").json() == {"ok": True, "db": True, "ai": True}
    assert len(login().get("/api/examples").json()) == 2
