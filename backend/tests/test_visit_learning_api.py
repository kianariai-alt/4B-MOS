"""Synthetic HTTP boundaries; no external delivery or real patient audio."""
import json

import pytest

from backend.app.core.security import create_access_token
from backend.tests.test_visit_learning import prepare, submission, user, configure_local_crypto


def headers(actor):
    return {"Authorization": "Bearer " + create_access_token(subject=actor.id, auth_version=actor.auth_version)}


def test_learning_http_roles_stream_limit_and_no_store(client, db_session):
    for endpoint in ("/visit-learning", "/recording-inbox"):
        response = client.get("/api/v1" + endpoint)
        assert response.status_code == 401
        assert response.headers["cache-control"] == "no-store"
    for role in ("admin", "operator", "nurse", "viewer"):
        actor = user(db_session, role)
        for endpoint in ("/visit-learning", "/recording-inbox"):
            assert client.get("/api/v1" + endpoint, headers=headers(actor)).status_code == 403
    context = prepare(db_session)
    target = "/api/v1/visits/" + context["visit"].id + "/visit-learning"
    auth = headers(context["actor"])
    assert client.post(target, headers={**auth, "Content-Type": "text/plain"}, content="not JSON").status_code == 415
    oversized = client.post(target, headers={**auth, "Content-Type": "application/json"}, content=b" " * (1024 * 1024 + 1))
    assert oversized.status_code == 413 and oversized.headers["cache-control"] == "no-store"
    invalid = client.post(target, headers=auth, json={"private_example": "SYNTHETIC-NO-ECHO"})
    assert invalid.status_code == 422 and "SYNTHETIC-NO-ECHO" not in invalid.text


def test_learning_http_submission_download_preview_and_draft_only(client, db_session):
    context = prepare(db_session)
    actor = context["actor"]
    auth = headers(actor)
    command = submission(context)
    response = client.post("/api/v1/visits/" + context["visit"].id + "/visit-learning",
                           headers=auth, json=command.model_dump(mode="json"))
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["packet"]["packet_id"] == command.packet.packet_id
    root = "/api/v1/visit-learning/" + command.packet.packet_id
    exported = client.get(root + "/download", headers=auth)
    assert exported.status_code == 200 and exported.json() == command.packet.model_dump(mode="json")
    assert exported.headers["cache-control"] == "no-store" and "attachment" in exported.headers["content-disposition"]
    assert client.get(root + "/bank-preview", headers=auth).json()["bank"]["questions"]
    promoted = client.post(root + "/bank-draft", headers=auth, json={
        "expected_version": body["summary"]["version"], "expected_packet_sha256": body["summary"]["packet_sha256"],
        "expected_bank_version": 0, "request_key": "synthetic-http-promote", "statement_fa": "توالی و هویت‌زدایی پرسش‌های ساختگی برای پیش‌نویس مرور شدند.",
    })
    assert promoted.status_code == 201, promoted.text
    assert promoted.json()["bank_event"]["action"] == "draft"
    assert promoted.json()["activation_performed"] is False
    style = client.get("/api/v1/visits/" + context["visit"].id + "/interview-style", headers=auth)
    assert style.status_code == 200 and style.json()["has_approved_bank"] is False
    inbox = client.get("/api/v1/recording-inbox", headers=auth)
    assert inbox.status_code == 200 and inbox.json()["items"][0]["capture_origin"]["room_code"] == "room-1"
    page = client.get("/app/visit-learning.html")
    assert page.status_code == 200 and page.headers["cache-control"] == "no-store"
    assert "microphone=()" in page.headers["permissions-policy"]
