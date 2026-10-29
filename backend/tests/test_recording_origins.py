"""Synthetic direct-service checks for independent, consent-bound room capture."""
from datetime import datetime, timezone
from types import SimpleNamespace
import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select

from backend.app.api.routes import recording as recording_routes
from backend.app.models.patient import Patient
from backend.app.models.recording import VisitRecordingEvent
from backend.app.models.user import User
from backend.app.models.visit import Visit
from backend.app.schemas.capture_origin import CaptureOrigin
from backend.app.schemas.reception import ConsentCreate, ReceptionCreate
from backend.app.schemas.recording import RecordingFinish, RecordingStart
from backend.app.services.recording import (
    RecordingConflictError, RecordingService, normalized_command,
)
from backend.app.services.reception import ReceptionService
from backend.app.services.session_finalization import evidence_digest


def origin(room="room-a", *, device=None, session=None):
    return {
        "room_code": room,
        "device_id": device or str(uuid.uuid4()),
        "client_session_id": session or str(uuid.uuid4()),
    }


def prepare(db, *, consent_granted=True):
    physician = User(username="synthetic-room-doctor", display_name="Synthetic Doctor",
                     password_hash="synthetic-not-a-login-secret", role="physician", is_active=True)
    patient = Patient(patient_code="SYNTHETIC-ROOM", first_name="Synthetic", last_name="Patient")
    db.add_all([physician, patient]); db.commit()
    visits = [Visit(patient_id=patient.id, status="open", chief_complaint="Synthetic complaint") for _ in range(2)]
    db.add_all(visits); db.commit()
    consents = []
    for index, visit in enumerate(visits):
        ReceptionService.save_intake(db, visit.id, ReceptionCreate(
            patient_reported_complaint="Synthetic statement", assigned_physician_id=physician.id,
            expected_version=0, request_key=f"room-intake-{index}"), actor=physician)
        consent = None
        if consent_granted:
            consent = ReceptionService.record_consent(db, visit.id, ConsentCreate(
                purpose="audio_recording", state="granted", document_version="SYNTHETIC-1",
                evidence_reference="SYNTHETIC-ROOM-CONSENT", confirmed_at=datetime.now(timezone.utc),
                expected_version=0, request_key=f"room-consent-{index}"), actor=physician)
        consents.append(consent)
    return SimpleNamespace(physician=physician, visits=visits, consents=consents)


def start_data(consent_sha, **changes):
    return {
        "recording_id": str(uuid.uuid4()), "expected_version": 0,
        "request_key": "room-start-0001", "expected_consent_sha256": consent_sha,
        **changes,
    }


def test_legacy_start_receipt_remains_byte_bound_and_retryable(db_session):
    setup = prepare(db_session)
    visit, consent = setup.visits[0], setup.consents[0]
    command = start_data(consent.sha256)
    now = datetime.now(timezone.utc)
    body = dict(id=str(uuid.uuid4()), visit_id=visit.id, recording_id=command["recording_id"],
                version=1, action="start", recorded_by=setup.physician.id, created_at=now.isoformat(),
                request_key=command["request_key"], command=command,
                consent_event_id=consent.id, consent_sha256=consent.sha256)
    expected_sha = evidence_digest(body)
    # Persist exactly the old schema's event, with no newly invented null key.
    db_session.add(VisitRecordingEvent(**{key: body[key] for key in (
        "id", "visit_id", "recording_id", "version", "action", "recorded_by", "request_key")},
        created_at=now, payload=body, sha256=expected_sha))
    db_session.commit()
    new_request = RecordingStart(**command, capture_origin=None)
    result = RecordingService.start(db_session, visit.id, new_request, actor=setup.physician)
    assert result.id == body["id"] and result.sha256 == expected_sha
    assert result.command == command and "capture_origin" not in result.command
    assert db_session.scalar(select(func.count()).select_from(VisitRecordingEvent)) == 1


def test_new_start_without_origin_keeps_the_legacy_command_shape(db_session):
    setup = prepare(db_session)
    command = start_data(setup.consents[0].sha256)
    result = RecordingService.start(db_session, setup.visits[0].id,
                                    RecordingStart(**command), actor=setup.physician)
    assert result.command == command
    assert normalized_command(RecordingStart(**command, capture_origin=None)) == command
    assert evidence_digest(result.model_dump(mode="json", exclude={"sha256"})) == result.sha256


def test_two_visits_record_independently_from_distinct_room_devices(db_session):
    setup = prepare(db_session)
    sources = [origin("room-a"), origin("room-b")]
    receipts = []
    for visit, consent, source in zip(setup.visits, setup.consents, sources, strict=True):
        receipts.append(RecordingService.start(db_session, visit.id,
            RecordingStart(**start_data(consent.sha256, capture_origin=source)), actor=setup.physician))
    assert receipts[0].recording_id != receipts[1].recording_id
    assert all(receipt.version == 1 for receipt in receipts)
    for visit, receipt, source in zip(setup.visits, receipts, sources, strict=True):
        access = RecordingService.access(db_session, visit.id, actor=setup.physician)
        assert access.active_recording.id == receipt.id
        assert access.active_recording.command["capture_origin"] == source
        assert set(access.active_recording.command["capture_origin"]) == {"room_code", "device_id", "client_session_id"}
        assert RecordingService.check(db_session, visit.id, receipt.recording_id,
                                      actor=setup.physician).can_continue


def test_same_visit_cannot_overlap_across_room_devices_and_maps_to_409(db_session):
    setup = prepare(db_session)
    visit, consent = setup.visits[0], setup.consents[0]
    first = RecordingService.start(db_session, visit.id,
        RecordingStart(**start_data(consent.sha256, capture_origin=origin("room-a"))), actor=setup.physician)
    other = RecordingStart(**start_data(consent.sha256, expected_version=1,
        request_key="room-start-0002", capture_origin=origin("room-b")))
    with pytest.raises(HTTPException) as failure:
        recording_routes.start(visit.id, other, actor=setup.physician, db=db_session)
    assert failure.value.status_code == 409
    assert RecordingService.access(db_session, visit.id, actor=setup.physician).active_recording.id == first.id
    assert db_session.scalar(select(func.count()).select_from(VisitRecordingEvent)) == 1


@pytest.mark.parametrize("changed_field", ["room_code", "device_id", "client_session_id"])
def test_request_key_cannot_be_reused_with_a_different_origin(db_session, changed_field):
    setup = prepare(db_session)
    source = origin()
    command = start_data(setup.consents[0].sha256, capture_origin=source)
    first = RecordingService.start(db_session, setup.visits[0].id, RecordingStart(**command), actor=setup.physician)
    assert RecordingService.start(db_session, setup.visits[0].id,
                                 RecordingStart(**command), actor=setup.physician).sha256 == first.sha256
    changed = {**source, changed_field: "room-b" if changed_field == "room_code" else str(uuid.uuid4())}
    with pytest.raises(HTTPException) as failure:
        recording_routes.start(setup.visits[0].id, RecordingStart(**{**command, "capture_origin": changed}),
                               actor=setup.physician, db=db_session)
    assert failure.value.status_code == 409


def test_finish_retains_legacy_null_checksum_and_does_not_repeat_capture_origin(db_session):
    setup = prepare(db_session)
    start = RecordingService.start(db_session, setup.visits[0].id,
        RecordingStart(**start_data(setup.consents[0].sha256, capture_origin=origin())), actor=setup.physician)
    command = dict(recording_id=start.recording_id, expected_version=1, request_key="room-finish-0001",
                   reason="microphone_error", pcm_bytes=0, encrypted_file_sha256=None)
    finish = RecordingFinish(**command)
    assert normalized_command(finish) == command
    result = RecordingService.finish(db_session, setup.visits[0].id, finish, actor=setup.physician)
    assert result.command == command and "capture_origin" not in result.command
    assert RecordingService.finish(db_session, setup.visits[0].id, finish, actor=setup.physician).sha256 == result.sha256


def test_reported_origin_does_not_replace_missing_recording_consent(db_session):
    setup = prepare(db_session, consent_granted=False)
    with pytest.raises(RecordingConflictError):
        RecordingService.start(db_session, setup.visits[0].id,
            RecordingStart(**start_data("0" * 64, capture_origin=origin())), actor=setup.physician)
    assert db_session.scalar(select(func.count()).select_from(VisitRecordingEvent)) == 0


def test_source_metadata_does_not_renew_permission_after_consent_withdrawal(db_session):
    setup = prepare(db_session)
    visit = setup.visits[0]
    command = RecordingStart(**start_data(setup.consents[0].sha256, capture_origin=origin()))
    first = RecordingService.start(db_session, visit.id, command, actor=setup.physician)
    ReceptionService.record_consent(db_session, visit.id, ConsentCreate(
        purpose="audio_recording", state="withdrawn", document_version="SYNTHETIC-1",
        evidence_reference="SYNTHETIC-ROOM-WITHDRAWAL", confirmed_at=datetime.now(timezone.utc),
        expected_version=1, request_key="room-withdrawal-01"), actor=setup.physician)
    retry = RecordingService.start(db_session, visit.id, command, actor=setup.physician)
    assert retry.id == first.id
    assert not RecordingService.check(db_session, visit.id, first.recording_id, actor=setup.physician).can_continue


@pytest.mark.parametrize("changes", [
    {"room_code": ""}, {"room_code": "a" * 81}, {"room_code": "room a"},
    {"room_code": "اتاق-یک"}, {"room_code": "room@example.test"}, {"room_code": "../room"},
    {"room_code": 1}, {"room_code": True}, {"device_id": "not-a-uuid"},
    {"client_session_id": "not-a-uuid"}, {"device_id": 1}, {"client_session_id": True},
    {"patient_name": "SYNTHETIC-PATIENT"}, {"patient_id": "SYNTHETIC-ID"},
    {"authenticated_hardware": True}, {"email": "synthetic@example.test"},
])
def test_origin_accepts_only_minimum_typed_source_identifiers(changes):
    with pytest.raises(ValidationError):
        CaptureOrigin(**{**origin(), **changes})


def test_origin_is_immutable_and_roundtrips_only_minimum_fields():
    payload = origin("room_1-east.2")
    parsed = CaptureOrigin(**payload)
    assert parsed.model_dump(mode="json") == payload
    with pytest.raises(ValidationError):
        parsed.room_code = "room-b"
