"""Synthetic central discovery without plaintext, cross-room mixing or stale access."""
import base64
from datetime import datetime, timezone
import hashlib
import uuid

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import func, select, text

from backend.app.core.config import settings
from backend.app.models.recording import VisitRecordingEvent
from backend.app.models.recording_media import RecordingAudioTransfer, RecordingTextEvent
from backend.app.models.user import User
from backend.app.schemas.reception import ConsentCreate, ReceptionCreate
from backend.app.schemas.recording import RecordingFinish, RecordingStart
from backend.app.schemas.recording_media import CompleteAudio, InitializeAudio, TextCommand
from backend.app.services import recording_media
from backend.app.services.recording import RecordingAuthorizationError, RecordingConflictError, RecordingService
from backend.app.services.recording_inbox import list_recording_inbox
from backend.app.services.reception import ReceptionService
from backend.tests.test_recording_origins import origin, prepare, start_data


@pytest.fixture(autouse=True)
def disabled_audio_by_default(monkeypatch):
    monkeypatch.setattr(settings, "AUDIO_PIPELINE_ENABLED", False)


def capture(db, visit, doctor, consent, *, source=None, reason="finished", complete=True):
    start = RecordingService.start(db, visit.id, RecordingStart(**start_data(
        consent.sha256, capture_origin=source)), actor=doctor)
    if complete:
        RecordingService.finish(db, visit.id, RecordingFinish(
            recording_id=start.recording_id, expected_version=1, request_key="inbox-finish-0001",
            reason=reason, pcm_bytes=32000, encrypted_file_sha256="a" * 64), actor=doctor)
    return start


def change_consent(db, visit, physician, *, state, version, key):
    return ReceptionService.record_consent(db, visit.id, ConsentCreate(
        purpose="audio_recording", state=state, document_version="SYNTHETIC-1",
        evidence_reference="SYNTHETIC-INBOX-CONSENT", confirmed_at=datetime.now(timezone.utc),
        expected_version=version, request_key=key), actor=physician)


def second_doctor(db):
    doctor = User(username="synthetic-inbox-other", display_name="Synthetic Other Doctor",
                  password_hash="synthetic-not-a-login-secret", role="physician", is_active=True)
    db.add(doctor); db.commit()
    return doctor


def assign(db, visit, original_doctor, new_doctor):
    ReceptionService.save_intake(db, visit.id, ReceptionCreate(
        patient_reported_complaint="Synthetic re-assignment", assigned_physician_id=new_doctor.id,
        expected_version=1, request_key="inbox-reassign-0001"), actor=original_doctor)


def test_other_computer_can_discover_two_completed_room_recordings_without_device_credentials(db_session):
    setup = prepare(db_session)
    sources = [origin("room-a"), origin("room-b")]
    starts = [capture(db_session, visit, setup.physician, consent, source=source)
              for visit, consent, source in zip(setup.visits, setup.consents, sources, strict=True)]
    # The inbox requires fresh doctor authorization, not a local DPAPI audio
    # file or device identity, so another authorized computer can discover it.
    result = list_recording_inbox(db_session, actor=setup.physician)
    assert {item.recording_id for item in result.items} == {item.recording_id for item in starts}
    assert {item.capture_origin.room_code for item in result.items} == {"room-a", "room-b"}
    assert all(item.media_state == "not_uploaded" and not item.audio_received for item in result.items)
    assert all(item.captured_at.utcoffset().total_seconds() == 0 for item in result.items)
    assert not result.audio_upload_enabled and not result.transcription_enabled
    assert not result.origin_is_authenticated_hardware and not result.training_enabled
    assert result.next_offset is None


def test_room_filter_is_exact_and_missing_legacy_origin_is_not_invented(db_session):
    setup = prepare(db_session)
    first = capture(db_session, setup.visits[0], setup.physician, setup.consents[0], source=origin("room-a"))
    legacy = capture(db_session, setup.visits[1], setup.physician, setup.consents[1])
    result = list_recording_inbox(db_session, actor=setup.physician)
    unknown = next(item for item in result.items if item.recording_id == legacy.recording_id)
    assert unknown.capture_origin is None and unknown.origin_missing_for_legacy
    filtered = list_recording_inbox(db_session, actor=setup.physician, room_code="room-a")
    assert [item.recording_id for item in filtered.items] == [first.recording_id]
    assert not list_recording_inbox(db_session, actor=setup.physician, room_code="room").items
    assert not list_recording_inbox(db_session, actor=setup.physician, room_code="ROOM-A").items


def test_pagination_is_bounded_deterministic_and_contains_only_owned_authorized_rows(db_session):
    setup = prepare(db_session)
    for visit, consent in zip(setup.visits, setup.consents, strict=True):
        capture(db_session, visit, setup.physician, consent, source=origin())
    whole = list_recording_inbox(db_session, actor=setup.physician)
    first = list_recording_inbox(db_session, actor=setup.physician, limit=1)
    second = list_recording_inbox(db_session, actor=setup.physician, limit=1, offset=first.next_offset)
    assert first.next_offset == 1 and second.next_offset is None
    assert first.items + second.items == whole.items
    assert not list_recording_inbox(db_session, actor=setup.physician, offset=2).items


def test_other_physician_never_receives_recordings_or_count_information(db_session):
    setup = prepare(db_session)
    capture(db_session, setup.visits[0], setup.physician, setup.consents[0], source=origin())
    other = second_doctor(db_session)
    result = list_recording_inbox(db_session, actor=other, limit=1)
    assert result.items == () and result.next_offset is None
    assert "total" not in result.model_dump()


def test_reassigned_recording_is_hidden_from_both_original_and_new_doctor(db_session):
    setup = prepare(db_session)
    capture(db_session, setup.visits[0], setup.physician, setup.consents[0], source=origin())
    other = second_doctor(db_session)
    assign(db_session, setup.visits[0], setup.physician, other)
    assert not list_recording_inbox(db_session, actor=setup.physician).items
    assert not list_recording_inbox(db_session, actor=other).items


def test_withdrawn_recording_does_not_affect_authorized_page_positions(db_session):
    setup = prepare(db_session)
    for visit, consent in zip(setup.visits, setup.consents, strict=True):
        capture(db_session, visit, setup.physician, consent, source=origin())
    change_consent(db_session, setup.visits[1], setup.physician, state="withdrawn", version=1,
                   key="inbox-withdraw-0001")
    result = list_recording_inbox(db_session, actor=setup.physician, limit=1)
    assert len(result.items) == 1 and result.items[0].visit_id == setup.visits[0].id
    assert result.next_offset is None


def test_new_audio_consent_grant_does_not_reauthorize_old_recording(db_session):
    setup = prepare(db_session)
    capture(db_session, setup.visits[0], setup.physician, setup.consents[0], source=origin())
    change_consent(db_session, setup.visits[0], setup.physician, state="withdrawn", version=1,
                   key="inbox-withdraw-0001")
    change_consent(db_session, setup.visits[0], setup.physician, state="granted", version=2,
                   key="inbox-regrant-0001")
    assert not list_recording_inbox(db_session, actor=setup.physician).items


@pytest.mark.parametrize("role", ["admin", "operator", "nurse", "viewer"])
def test_nonphysician_roles_cannot_list_inbox(db_session, role):
    setup = prepare(db_session)
    setup.physician.role = role; db_session.commit()
    with pytest.raises(RecordingAuthorizationError):
        list_recording_inbox(db_session, actor=setup.physician)


def test_inactive_physician_cannot_list_inbox(db_session):
    setup = prepare(db_session)
    setup.physician.is_active = False; db_session.commit()
    with pytest.raises(RecordingAuthorizationError):
        list_recording_inbox(db_session, actor=setup.physician)


def test_active_and_abnormally_finished_captures_are_not_offered_as_transferable(db_session):
    setup = prepare(db_session)
    capture(db_session, setup.visits[0], setup.physician, setup.consents[0], source=origin(), complete=False)
    capture(db_session, setup.visits[1], setup.physician, setup.consents[1], source=origin(), reason="connection_lost")
    assert not list_recording_inbox(db_session, actor=setup.physician).items


def test_closed_visit_remains_reviewable_with_current_exact_consent(db_session):
    setup = prepare(db_session)
    start = capture(db_session, setup.visits[0], setup.physician, setup.consents[0], source=origin())
    setup.visits[0].status = "closed"; db_session.commit()
    result = list_recording_inbox(db_session, actor=setup.physician)
    assert [item.recording_id for item in result.items] == [start.recording_id]


def test_returned_media_state_does_not_decrypt_or_export_transcript(db_session, monkeypatch):
    setup = prepare(db_session)
    start = capture(db_session, setup.visits[0], setup.physician, setup.consents[0], source=origin())
    monkeypatch.setattr(settings, "AUDIO_PIPELINE_ENABLED", True)
    monkeypatch.setattr(settings, "AUDIO_ENCRYPTION_KEY", SecretStr(base64.b64encode(b"k" * 32).decode()))
    monkeypatch.setattr(recording_media, "_speech_ready", lambda: True)
    pcm = b"\0" * 32000
    pcm_sha = hashlib.sha256(pcm).hexdigest()
    recording_media.RecordingMediaService.initialize(db_session, setup.visits[0].id, start.recording_id,
        InitializeAudio(request_key="inbox-audio-init", pcm_bytes=len(pcm), pcm_sha256=pcm_sha,
                        encrypted_file_sha256="a" * 64), actor=setup.physician)
    recording_media.RecordingMediaService.put_chunk(db_session, setup.visits[0].id, start.recording_id,
                                                    0, pcm, pcm_sha, actor=setup.physician)
    recording_media.RecordingMediaService.complete(db_session, setup.visits[0].id, start.recording_id,
        CompleteAudio(request_key="inbox-audio-complete", expected_pcm_sha256=pcm_sha), actor=setup.physician)
    recording_media.RecordingMediaService.enqueue(db_session, setup.visits[0].id, start.recording_id,
        TextCommand(expected_version=1, request_key="inbox-speech-queue"), actor=setup.physician)
    claim = recording_media.RecordingMediaService.claim(db_session, setup.visits[0].id, start.recording_id)
    content = {"text": "SYNTHETIC-DO-NOT-EXPORT", "model_id": "synthetic-test-only",
               "model_fingerprint": "b" * 64, "segments": [{"start": 0, "end": 1, "text": "SYNTHETIC-DO-NOT-EXPORT"}]}
    recording_media.RecordingMediaService.finish_job(db_session, setup.visits[0].id, start.recording_id, claim, content)
    counts = [db_session.scalar(select(func.count()).select_from(model))
              for model in (VisitRecordingEvent, RecordingAudioTransfer, RecordingTextEvent)]
    def forbidden_decrypt(*args, **kwargs):
        raise AssertionError("Inbox must not decrypt a media or transcript payload.")
    monkeypatch.setattr(recording_media, "decrypt", forbidden_decrypt)
    result = list_recording_inbox(db_session, actor=setup.physician)
    assert result.items[0].media_state == "draft" and result.items[0].audio_received
    assert result.audio_upload_enabled and result.transcription_enabled
    payload = result.model_dump_json()
    assert "SYNTHETIC-DO-NOT-EXPORT" not in payload
    assert "patient_code" not in payload and "first_name" not in payload and "edited_text" not in payload
    assert not result.contains_transcript_text
    assert counts == [db_session.scalar(select(func.count()).select_from(model))
                      for model in (VisitRecordingEvent, RecordingAudioTransfer, RecordingTextEvent)]


def test_transcription_is_not_reported_ready_when_audio_pipeline_is_disabled(db_session, monkeypatch):
    setup = prepare(db_session)
    monkeypatch.setattr(recording_media, "_speech_ready", lambda: True)
    result = list_recording_inbox(db_session, actor=setup.physician)
    assert not result.audio_upload_enabled and not result.transcription_enabled


def test_tampered_recording_metadata_fails_closed_without_listing(db_session):
    setup = prepare(db_session)
    start = capture(db_session, setup.visits[0], setup.physician, setup.consents[0], source=origin())
    db_session.execute(text("UPDATE visit_recording_events SET sha256=:bad WHERE id=:id"),
                       {"bad": "0" * 64, "id": start.id}); db_session.commit()
    with pytest.raises(RecordingConflictError):
        list_recording_inbox(db_session, actor=setup.physician)


@pytest.mark.parametrize("changes", [
    {"limit": 0}, {"limit": 101}, {"limit": True}, {"limit": "1"},
    {"offset": -1}, {"offset": True}, {"offset": "0"},
    {"room_code": ""}, {"room_code": "room a"}, {"room_code": "a" * 81},
    {"room_code": "room@example.test"}, {"room_code": "اتاق"},
])
def test_list_parameters_are_strict_and_bounded(db_session, changes):
    setup = prepare(db_session)
    with pytest.raises(ValidationError):
        list_recording_inbox(db_session, actor=setup.physician, **changes)
