from datetime import timedelta, timezone

import pytest
from sqlalchemy import select

from backend.app.core.config import settings
from backend.app.models.physician_questions import PhysicianQuestionEvent
from backend.app.services.physician_questions import _read, QuestionBankConflictError
from backend.tests.test_patient_portal import portal, start, submit, API, ORIGIN
from backend.tests.test_physician_questions import setup, draft, review

pytestmark = pytest.mark.usefixtures("authenticated_admin")


def bank(client, db, monkeypatch):
    headers, physician, root = setup(client, db)
    content = draft()
    content["questions"] = [
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
