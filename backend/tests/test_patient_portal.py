import base64
import io
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image
from sqlalchemy import func, select

from backend.app.core.config import Settings, settings
from backend.app.models.patient import Patient
from backend.app.models.patient_portal import PortalAccess, PortalAttachment, PortalMessage, PortalRequest, PortalSession
from backend.app.models.user import User
from backend.app.models.visit import Visit
from backend.app.models.reception import VisitConsentEvent
from backend.app.services.patient_portal import content, decrypt

ORIGIN = "http://testserver"
API = "/api/v1/patient-portal"
STAFF = "/api/v1/portal-staff"


@pytest.fixture
def portal(monkeypatch):
    from pydantic import SecretStr
    monkeypatch.setattr(settings, "PATIENT_PORTAL_ENABLED", True)
    monkeypatch.setattr(settings, "PATIENT_PORTAL_ORIGIN", ORIGIN)
    monkeypatch.setattr(settings, "PATIENT_PORTAL_KEY", SecretStr(base64.b64encode(bytes(range(32))).decode()))


def start(client):
    response = client.post(API + "/session", headers={"Origin": ORIGIN})
    assert response.status_code == 200, response.text
    return {"Origin": ORIGIN, "X-Portal-CSRF": response.json()["csrf_token"]}


def data(**changes):
    result = dict(request_key="synthetic-request", entry_mode="clinic_arrival", first_name="Synthetic",
        last_name="Patient", complaint="Synthetic knee complaint", conditions=["Synthetic condition"],
        processing_notice_version="portal-processing-v1", processing_consent=True)
    result.update(changes)
    return result


def submit(client, headers, **changes):
    response = client.post(API + "/requests", json=data(**changes), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def grant(db, username="testadmin"):
    user = db.scalar(select(User).where(User.username == username))
    db.add(PortalAccess(user_id=user.id, active=True))
    db.commit()
    return user


def image():
    output = io.BytesIO()
    Image.new("RGB", (20, 20), (20, 100, 180)).save(output, format="PNG")
    return output.getvalue()


def test_disabled_by_default(client):
    assert client.get(API + "/info").status_code == 404


def test_submit_is_encrypted_and_idempotent(portal, client, db_session):
    headers = start(client)
    result = submit(client, headers)
    assert submit(client, headers) == result
    assert client.post(API + "/requests", json=data(complaint="Different complaint"), headers=headers).status_code == 409
    row = db_session.get(PortalRequest, result["id"])
    assert b"Synthetic" not in row.encrypted_content
    assert content(row)["complaint"] == "Synthetic knee complaint"
    assert db_session.scalar(select(func.count()).select_from(PortalRequest)) == 1
    assert db_session.scalar(select(func.count()).select_from(Visit)) == 0
    own = client.get(API + "/requests/" + result["id"]).json()
    assert own["identity_status"] == "unverified_patient_report"
    assert own["content"]["pain_score"] is None
    assert own["content"]["marketing_opt_in"] is False


def test_origin_csrf_and_session_ownership(portal, client):
    assert client.post(API + "/session", headers={"Origin": "https://other.example"}).status_code == 403
    headers = start(client)
    result = submit(client, headers)
    assert client.post(API + "/requests", json=data(), headers={"Origin": ORIGIN}).status_code == 403
    client.cookies.clear()
    start(client)
    assert client.get(API + "/requests/" + result["id"]).status_code == 404
    assert client.post(API + "/requests/" + result["id"] + "/messages", headers=headers, json={"request_key": "reply-123", "text": "Test reply"}).status_code == 403


def test_staff_requires_explicit_grant_and_audits_acceptance(portal, client, admin_headers, db_session):
    headers = start(client)
    result = submit(client, headers, medications=[{"name": "Synthetic medicine"}], other_specialists=["Synthetic nephrology"])
    assert client.get(STAFF + "/requests", headers=admin_headers).status_code == 403
    grant(db_session)
    response = client.get(STAFF + "/requests/" + result["id"], headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["content"]["other_specialists"] == ["Synthetic nephrology"]
    write = {**admin_headers, "Origin": ORIGIN}
    assert client.post(STAFF + "/requests/" + result["id"] + "/accept", json={"identity_checked": False}, headers=write).status_code == 422
    accepted = client.post(STAFF + "/requests/" + result["id"] + "/accept", json={"identity_checked": True}, headers=write)
    assert accepted.status_code == 200, accepted.text
    visit_source = STAFF + "/visits/" + accepted.json()["visit_id"] + "/patient-report"
    report = client.get(visit_source, headers=admin_headers)
    assert report.status_code == 200
    assert report.json()["content"]["complaint"] == "Synthetic knee complaint"
    assert client.get(STAFF + "/visits/unlinked/patient-report", headers=admin_headers).json() is None
    assert client.get(visit_source).status_code == 401

    assert client.post(STAFF + "/requests/" + result["id"] + "/accept", json={"identity_checked": True}, headers=write).json() == accepted.json()
    assert db_session.scalar(select(func.count()).select_from(Patient)) == 1
    assert db_session.scalar(select(func.count()).select_from(Visit)) == 1
    assert db_session.scalar(select(func.count()).select_from(VisitConsentEvent)) == 0
    from backend.app.services.reception import ReceptionService
    workspace = ReceptionService.workspace(db_session, accepted.json()["visit_id"])
    assert workspace.latest_intake.content["patient_reported_complaint"] == "Synthetic knee complaint"


def test_existing_patient_not_overwritten(portal, client, admin_headers, db_session):
    grant(db_session)
    p = Patient(patient_code="EXISTING", first_name="Verified", last_name="Existing")
    db_session.add(p)
    db_session.commit()
    result = submit(client, start(client))
    response = client.post(STAFF + "/requests/" + result["id"] + "/accept", json={"identity_checked": True, "existing_patient_id": p.id}, headers={**admin_headers, "Origin": ORIGIN})
    assert response.status_code == 200, response.text
    db_session.refresh(p)
    assert p.first_name == "Verified"
    assert db_session.scalar(select(func.count()).select_from(Patient)) == 1


def test_questions_replies_and_withdrawal(portal, client, admin_headers, db_session):
    grant(db_session)
    headers = start(client)
    result = submit(client, headers)
    path = "/requests/" + result["id"]
    question = {"request_key": "question-123", "text": "Synthetic follow-up question?"}
    assert client.post(STAFF + path + "/messages", json=question, headers={**admin_headers, "Origin": ORIGIN}).status_code == 201
    assert client.get(API + path).json()["messages"][0]["from"] == "clinician"
    reply = {"request_key": "reply-123", "text": "Synthetic answer"}
    assert client.post(API + path + "/messages", json=reply, headers=headers).status_code == 201
    assert client.post(API + path + "/messages", json=reply, headers=headers).status_code == 201
    assert db_session.scalar(select(func.count()).select_from(PortalMessage)) == 2
    assert client.post(API + path + "/withdraw", headers=headers).status_code == 200
    assert client.post(API + path + "/messages", json=reply, headers=headers).status_code == 409
    assert client.post(STAFF + path + "/accept", json={"identity_checked": True}, headers={**admin_headers, "Origin": ORIGIN}).status_code == 409


def test_images_rewritten_encrypted_scoped_and_download_audited(portal, client, admin_headers, db_session):
    grant(db_session)
    headers = start(client)
    result = submit(client, headers)
    path = "/requests/" + result["id"]
    invalid = client.post(API + path + "/attachments", content=b"%PDF-test", headers=headers)
    assert invalid.status_code == 422
    response = client.post(API + path + "/attachments", content=image(), headers=headers)
    assert response.status_code == 201, response.text
    fid = response.json()["id"]
    assert client.post(API + path + "/attachments", content=image(), headers=headers).json()["id"] == fid
    file = db_session.get(PortalAttachment, fid)
    assert not file.encrypted_content.startswith(b"\x89PNG")
    assert decrypt(file.encrypted_content, "attachment:" + fid).startswith(b"\x89PNG")
    assert client.get(STAFF + path + "/attachments/" + fid).status_code == 401
    response = client.get(STAFF + path + "/attachments/" + fid, headers=admin_headers)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "attachment" in response.headers["content-disposition"]
    other = submit(client, headers, request_key="another-request")
    assert client.get(STAFF + "/requests/" + other["id"] + "/attachments/" + fid, headers=admin_headers).status_code == 404


def test_large_bodies_expiry_logout_and_throttle(portal, client, db_session):
    headers = start(client)
    assert client.post(API + "/requests", content=b"x" * 65537, headers=headers).status_code == 413
    assert client.post(API + "/requests/unknown/attachments", content=b"x" * (5 * 1024 * 1024 + 1), headers=headers).status_code == 413
    session = db_session.scalar(select(PortalSession))
    session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    assert client.post(API + "/requests", json=data(), headers=headers).status_code == 401
    client.cookies.clear()
    headers = start(client)
    assert client.post(API + "/logout", headers=headers).status_code == 200
    assert client.post(API + "/requests", json=data(), headers=headers).status_code == 401
    statuses = [client.post(API + "/session", headers={"Origin": ORIGIN}).status_code for _ in range(31)]
    assert 429 in statuses


def test_access_revocation_and_ciphertext_tamper(portal, client, admin_headers, db_session):
    user = grant(db_session)
    result = submit(client, start(client))
    row = db_session.get(PortalRequest, result["id"])
    row.encrypted_content = row.encrypted_content[:-1] + bytes([row.encrypted_content[-1] ^ 1])
    db_session.commit()
    assert client.get(API + "/requests/" + row.id).status_code == 409
    permission = db_session.get(PortalAccess, user.id)
    permission.active = False
    db_session.commit()
    assert client.get(STAFF + "/requests", headers=admin_headers).status_code == 403


def test_config_requires_key_and_public_https():
    with pytest.raises(ValueError):
        Settings(_env_file=None, PATIENT_PORTAL_ENABLED=True)
    key = base64.b64encode(bytes(range(32))).decode()
    for origin in ["http://clinic.example", "https://clinic.example/path", "https://clinic.example/", "https://user@clinic.example"]:
        with pytest.raises(ValueError):
            Settings(_env_file=None, PATIENT_PORTAL_ENABLED=True, PATIENT_PORTAL_KEY=key, PATIENT_PORTAL_ORIGIN=origin)
    assert Settings(_env_file=None, PATIENT_PORTAL_ENABLED=True, PATIENT_PORTAL_KEY=key, PATIENT_PORTAL_ORIGIN="https://patient.example").PATIENT_PORTAL_ENABLED
