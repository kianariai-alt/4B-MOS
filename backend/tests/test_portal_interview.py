from datetime import datetime, timedelta, timezone
import json

import pytest
from sqlalchemy import select

from backend.app.core.config import settings
from backend.app.models.physician_questions import PhysicianQuestionEvent
from backend.app.models.patient_portal import PortalInterview
from backend.app.services import patient_portal as portal_service
from backend.app.services.physician_questions import _read, QuestionBankConflictError
from backend.tests.test_patient_portal import portal, start, submit, API, ORIGIN
from backend.tests.test_physician_questions import setup, draft, review

pytestmark = pytest.mark.usefixtures("authenticated_admin")


def bank(client, db, monkeypatch, questions=None):
    headers, physician, root = setup(client, db)
    content = draft()
    content["questions"] = questions or [
        dict(id="one", text_fa="پرسش ساختگی اول؟", purpose_fa="آزمون سامانه", answer_type="yes_no"),
        dict(id="two", text_fa="پرسش ساختگی وابسته؟", purpose_fa="آزمون ترتیب", depends_on_id="one", show_when_answer_in=["yes"]),
        dict(id="three", text_fa="پرسش ساختگی سوم؟", purpose_fa="آزمون انتخاب", answer_type="single_choice", choices=["الف", "ب"]),
    ]
    first = client.post(root + "/drafts", json=content, headers=headers)
    assert first.status_code == 201, first.text
    approved = client.post(root + "/approve", json=review(first.json(), 1, "approve-portal-bank"), headers=headers)
    assert approved.status_code == 201, approved.text
    monkeypatch.setattr(settings, "PATIENT_PORTAL_QUESTION_BANKS", {"knee": physician})
    return headers, root, approved.json()


def test_governed_branching_retry_unknown_and_retirement(portal, client, admin_headers, db_session, monkeypatch):
    physician, root, approved = bank(client, db_session, monkeypatch)
    headers = start(client)
    request = submit(client, headers, body_region="knee")
    path = API + "/requests/" + request["id"]
    workspace = client.get(path).json()
    assert workspace["interview"]["next_question"]["id"] == "one"
    command = dict(request_key="answer-one", expected_version=0, question_id="one", state="answered", value="invalid")
    assert client.post(path + "/interview-answers", json=command, headers=headers).status_code == 422
    command["value"] = "yes"
    response = client.post(path + "/interview-answers", json=command, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["next_question"]["id"] == "two"
    assert client.post(path + "/interview-answers", json=command, headers=headers).json()["version"] == 1
    stale = dict(request_key="answer-two", expected_version=0, question_id="two", state="unknown", value=None)
    assert client.post(path + "/interview-answers", json=stale, headers=headers).status_code == 409
    stale["expected_version"] = 1
    response = client.post(path + "/interview-answers", json=stale, headers=headers)
    assert response.json()["next_question"]["id"] == "three"
    response = client.post(root + "/retire", json=review(approved, 2, "retire-portal-bank"), headers=physician)
    assert response.status_code == 201, response.text
    assert client.get(path).json()["interview"]["accepting_answers"] is False
    assert client.post(path + "/interview-answers", json=dict(request_key="answer-three", expected_version=2, question_id="three", state="answered", value="الف"), headers=headers).status_code == 409


def test_no_skips_children_and_complete_without_diagnosis(portal, client, admin_headers, db_session, monkeypatch):
    bank(client, db_session, monkeypatch)
    headers = start(client)
    request = submit(client, headers, body_region="knee")
    path = API + "/requests/" + request["id"]
    skipped = dict(request_key="skip-child", expected_version=0, question_id="two", state="answered", value="Test")
    assert client.post(path + "/interview-answers", json=skipped, headers=headers).status_code == 409
    response = client.post(path + "/interview-answers", json=dict(request_key="answer-root", expected_version=0, question_id="one", state="answered", value="no"), headers=headers)
    assert response.json()["next_question"]["id"] == "three"
    response = client.post(path + "/interview-answers", json=dict(request_key="answer-last", expected_version=1, question_id="three", state="declined", value=None), headers=headers)
    assert response.json()["complete"] is True
    assert response.json()["next_question"] is None
    assert "diagnosis" not in response.json()


def test_question_bank_timezone_integrity(portal, client, admin_headers, db_session, monkeypatch):
    bank(client, db_session, monkeypatch)
    row = db_session.scalar(select(PhysicianQuestionEvent).order_by(PhysicianQuestionEvent.version))
    timestamp = row.created_at.replace(tzinfo=timezone.utc) if row.created_at.tzinfo is None else row.created_at
    row.created_at = timestamp.astimezone(timezone(timedelta(hours=3, minutes=30)))
    assert _read(row).created_at == row.payload["created_at"]
    row.created_at += timedelta(seconds=1)
    with pytest.raises(QuestionBankConflictError):
        _read(row)
    db_session.rollback()


def test_correction_invalidates_descendants_preserves_history_and_never_resurrects(portal, client, db_session, monkeypatch):
    bank(client, db_session, monkeypatch)
    headers = start(client)
    request = submit(client, headers, body_region="knee")
    path = API + "/requests/" + request["id"]
    commands = [
        dict(request_key="correction-root", expected_version=0, question_id="one", state="answered", value="yes"),
        dict(request_key="correction-child", expected_version=1, question_id="two", state="answered", value="توضیح بیمار"),
        dict(request_key="correction-final", expected_version=2, question_id="three", state="declined", value=None),
    ]
    for command in commands:
        response = client.post(path + "/interview-answers", json=command, headers=headers)
        assert response.status_code == 200, response.text
    corrected = dict(request_key="correct-root-no", expected_version=3, question_id="one", state="answered", value="no")
    response = client.post(path + "/interview-answers", json=corrected, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["complete"] is True
    assert [answer["question_id"] for answer in body["answers"]] == ["one", "three"]
    assert len(body["answer_history"]) == 4
    child = next(event for event in body["answer_history"] if event["question_id"] == "two")
    assert child["value"] == "توضیح بیمار" and child["active"] is False
    assert child["invalidation"]["reason"] == "condition_no_longer_satisfied"
    assert child["invalidation"]["at_version"] == 4
    stale = {**corrected, "request_key": "stale-correction", "value": "yes"}
    assert client.post(path + "/interview-answers", json=stale, headers=headers).status_code == 409
    response = client.post(path + "/interview-answers", json={**stale, "request_key": "correct-root-yes", "expected_version": 4}, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["next_question"]["id"] == "two"
    assert "two" not in [answer["question_id"] for answer in response.json()["answers"]]
    # An old request key is still idempotent after that answer left the path.
    retry = client.post(path + "/interview-answers", json=commands[1], headers=headers)
    assert retry.status_code == 200 and retry.json()["version"] == 5
    assert retry.json()["next_question"]["id"] == "two"
    assert client.post(path + "/interview-answers", json={**commands[1], "value": "متن دیگر"}, headers=headers).status_code == 409
    assert len(retry.json()["answer_history"]) == 5


def test_numeric_zero_unit_and_summary_provenance(portal, client, db_session, monkeypatch):
    questions = [dict(id="synthetic_score", text_fa="امتیاز ساختگی آزمون؟", purpose_fa="آزمون عدد و واحد", answer_type="number",
        numeric_unit="test_point", numeric_min=0, numeric_max=10, question_version="test-1",
        provenance={"kind": "design_draft", "reference": "synthetic software test"})]
    bank(client, db_session, monkeypatch, questions)
    headers = start(client)
    request = submit(client, headers, body_region="knee")
    path = API + "/requests/" + request["id"]
    initial = client.get(path).json()["interview"]
    assert initial["assistant_summary"]["missing_question_ids"] == ["synthetic_score"]
    command = dict(request_key="numeric-zero", expected_version=0, question_id="synthetic_score", state="answered", value=0, unit="test_point", supplementary_text="متن تکمیلی")
    for change in ({"value": True}, {"value": "0"}, {"value": -1}, {"value": 11}, {"value": 10**1000}, {"unit": "other"}, {"unit": None}):
        response = client.post(path + "/interview-answers", json={**command, **change}, headers=headers)
        assert response.status_code == 422, response.text
    response = client.post(path + "/interview-answers", json=command, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["complete"] is True
    item = body["assistant_summary"]["items"][0]
    assert item["value"] == 0 and item["unit"] == "test_point"
    assert item["supplementary_text"] == "متن تکمیلی"
    assert item["source"] == "patient_portal" and item["bank_sha256"] == body["bank_sha256"]
    assert item["question_version"] == "test-1" and item["provenance"]["kind"] == "design_draft"
    assert datetime.fromisoformat(item["recorded_at"]).utcoffset() == timedelta(0)
    assert body["assistant_summary"]["missing_question_ids"] == []
    assert body["assistant_summary"]["patient_reported_only"] is True
    assert body["assistant_summary"]["requires_clinician_review"] is True
    assert "0 test_point" in body["assistant_summary"]["summary_fa"]
    assert not any(key in body["assistant_summary"] for key in ("diagnosis", "probability", "treatment"))


def test_compound_branching_and_explicit_unknown_route(portal, client, db_session, monkeypatch):
    def question(identifier, **fields):
        return dict(id=identifier, text_fa="پرسش ساختگی " + identifier, purpose_fa="آزمون نرم‌افزار", **fields)
    questions = [
        question("root", answer_type="yes_no"),
        question("score", answer_type="number", numeric_unit="test_point", numeric_min=0, numeric_max=10),
        question("both", display_condition={"all": [
            {"question_id": "root", "operator": "eq", "value": "yes"},
            {"question_id": "score", "operator": "gte", "value": 5}]}),
        question("uncertain", display_condition={"question_id": "root", "operator": "state_in", "states": ["unknown"]}),
        question("either", display_condition={"any": [
            {"question_id": "root", "operator": "eq", "value": "yes"},
            {"question_id": "score", "operator": "eq", "value": 0}]}),
    ]
    bank(client, db_session, monkeypatch, questions)
    headers = start(client)
    request = submit(client, headers, body_region="knee")
    path = API + "/requests/" + request["id"]
    def send(identifier, version, state="answered", value=None, unit=None):
        response = client.post(path + "/interview-answers", headers=headers, json=dict(request_key="compound-" + str(version), expected_version=version, question_id=identifier, state=state, value=value, unit=unit))
        assert response.status_code == 200, response.text
        return response.json()
    assert send("root", 0, "unknown")["next_question"]["id"] == "score"
    assert send("score", 1, value=0, unit="test_point")["next_question"]["id"] == "uncertain"
    assert send("uncertain", 2, "declined")["next_question"]["id"] == "either"
    finished = send("either", 3, value="پاسخ ساختگی")
    assert finished["complete"] is True
    assert finished["assistant_summary"]["unknown_question_ids"] == ["root"]
    assert finished["assistant_summary"]["declined_question_ids"] == ["uncertain"]
    assert finished["assistant_summary"]["inactive_question_ids"] == ["both"]
    # Correcting root simultaneously opens two eligible routes and invalidates
    # its explicit-unknown follow-up; it does not force a single pathway.
    revised = send("root", 4, value="yes")
    assert revised["next_question"] is None  # score remains zero, so 'both' stays inactive
    assert "uncertain" not in [item["question_id"] for item in revised["answers"]]
    revised = send("score", 5, value=7, unit="test_point")
    assert revised["next_question"]["id"] == "both"
    assert "either" in [item["question_id"] for item in revised["answers"]]


def test_legacy_encrypted_answers_migrate_without_invented_timestamp(portal, client, db_session, monkeypatch):
    bank(client, db_session, monkeypatch)
    headers = start(client)
    request = submit(client, headers, body_region="knee")
    path = API + "/requests/" + request["id"]
    command = dict(request_key="legacy-answer", expected_version=0, question_id="one", state="answered", value="yes")
    interview = db_session.get(PortalInterview, request["id"])
    interview.encrypted_answers = portal_service.encrypt(portal_service.encode({"one": command}), "interview-answers:" + request["id"])
    interview.version = 1
    db_session.commit()
    response = client.get(path).json()["interview"]
    assert response["answers"][0]["recorded_at"] is None
    assert response["answers"][0]["source"] == "legacy_patient_portal"
    assert response["answers"][0]["question_version"] == "legacy-unspecified"
    # New optional null payload fields do not invalidate legacy idempotency.
    retry = client.post(path + "/interview-answers", json={**command, "unit": None, "supplementary_text": None}, headers=headers)
    assert retry.status_code == 200 and retry.json()["version"] == 1
    response = client.post(path + "/interview-answers", json=dict(request_key="legacy-followup", expected_version=1, question_id="two", state="unknown", value=None), headers=headers)
    assert response.status_code == 200, response.text
    db_session.expire_all()
    interview = db_session.get(PortalInterview, request["id"])
    stored = json.loads(portal_service.decrypt(interview.encrypted_answers, "interview-answers:" + request["id"]))
    assert stored["schema_version"] == 2 and len(stored["answer_history"]) == 2
    assert stored["answer_history"][0]["command"] == command
    assert stored["answer_history"][0]["recorded_at"] is None


def test_multilevel_correction_keeps_full_encrypted_event_history(portal, client, db_session, monkeypatch):
    questions = [
        dict(id="root", text_fa="ریشه ساختگی؟", purpose_fa="آزمون سامانه", answer_type="yes_no"),
        dict(id="child", text_fa="فرزند ساختگی؟", purpose_fa="آزمون سامانه", answer_type="yes_no", depends_on_id="root", show_when_answer_in=["yes"]),
        dict(id="grandchild", text_fa="نوه ساختگی؟", purpose_fa="آزمون سامانه", depends_on_id="child", show_when_answer_in=["yes"]),
    ]
    bank(client, db_session, monkeypatch, questions)
    headers = start(client)
    request = submit(client, headers, body_region="knee")
    path = API + "/requests/" + request["id"]
    for version, (identifier, value) in enumerate((("root", "yes"), ("child", "yes"), ("grandchild", "نسخه قدیمی"), ("root", "no"))):
        response = client.post(path + "/interview-answers", headers=headers,
            json=dict(request_key="multi-answer-" + str(version), expected_version=version, question_id=identifier, state="answered", value=value))
        assert response.status_code == 200, response.text
    body = response.json()
    assert [item["question_id"] for item in body["answers"]] == ["root"]
    assert body["assistant_summary"]["inactive_question_ids"] == ["child", "grandchild"]
    assert len(body["answer_history"]) == 4
    assert all(not item["active"] for item in body["answer_history"][:3])
    assert all(item["invalidation"]["at_version"] == 4 for item in body["answer_history"][:3])
    db_session.expire_all()
    interview = db_session.get(PortalInterview, request["id"])
    assert "نسخه قدیمی".encode() not in interview.encrypted_answers
    stored = json.loads(portal_service.decrypt(interview.encrypted_answers, "interview-answers:" + request["id"]))
    assert stored["answer_history"][2]["command"]["value"] == "نسخه قدیمی"
    assert set(stored["active_answers"]) == {"root"}
