"""Synthetic direct-service checks for consent-bound interview-workflow learning.

These tests exercise storage, provenance and explicit question-bank draft
handoff. They do not claim speech accuracy, deidentification or model training.
"""
from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import uuid

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import func, select, text

from backend.app.core.config import settings
from backend.app.models.audit_log import AuditLog
from backend.app.models.clinical_safety import ClinicalSafetyRule
from backend.app.models.medical_knowledge import MedicalKnowledgeFact
from backend.app.models.patient import Patient
from backend.app.models.physician_questions import PhysicianQuestionEvent
from backend.app.models.recording_media import RecordingAudioTransfer
from backend.app.models.user import User
from backend.app.models.visit import Visit
from backend.app.models.visit_learning import VisitLearningEvent
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.schemas.physician_questions import BankReview, DraftCreate
from backend.app.schemas.reception import ConsentCreate, ReceptionCreate
from backend.app.schemas.recording import RecordingFinish, RecordingStart
from backend.app.schemas.recording_media import CompleteAudio, InitializeAudio, ReviewText, TextCommand
from backend.app.schemas.visit_learning import VisitLearningPacket, VisitLearningPromote, VisitLearningReviewCommand, VisitLearningSubmit
from backend.app.services.audio_crypto import AudioConfigurationError, AudioIntegrityError
from backend.app.services.physician_questions import PhysicianQuestionService
from backend.app.services.reception import ReceptionService
from backend.app.services.recording import RecordingService
from backend.app.services.recording_media import RecordingMediaService
from backend.app.services.session_finalization import evidence_digest
from backend.app.services.visit_learning import (
    VisitLearningAuthorizationError, VisitLearningConflictError,
    VisitLearningNotFoundError, VisitLearningService as Service,
    authorize_approved_bank_source,
)


TRANSCRIPT = "🙂 پزشک: درد شما از چه زمانی شروع شد؟\nبیمار: چند هفته است.\nپزشک: کدام فعالیت درد را بیشتر می‌کند؟"
QUESTIONS = ("درد شما از چه زمانی شروع شد؟", "کدام فعالیت درد را بیشتر می‌کند؟")


def identifier():
    return str(uuid.uuid4())


def request_key(prefix="synthetic"):
    return prefix + "-" + uuid.uuid4().hex


def sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@pytest.fixture(autouse=True)
def configure_local_crypto(monkeypatch):
    monkeypatch.setattr(settings, "AUDIO_PIPELINE_ENABLED", True)
    monkeypatch.setattr(settings, "AUDIO_ENCRYPTION_KEY", SecretStr(base64.b64encode(b"v" * 32).decode()))
    monkeypatch.setattr("backend.app.services.recording_media._speech_ready", lambda: True)


def user(db, role="physician"):
    actor = User(username="synthetic-" + uuid.uuid4().hex, display_name="Synthetic Clinician",
                 password_hash="not-a-login-password", role=role, is_active=True)
    db.add(actor)
    db.commit()
    return actor


def grant(db, visit_id, actor, purpose, *, state="granted"):
    workspace = ReceptionService.workspace(db, visit_id)
    return ReceptionService.record_consent(db, visit_id, ConsentCreate(
        purpose=purpose, state=state, document_version="SYNTHETIC-1",
        evidence_reference="SYNTHETIC-EXPLICIT-CONSENT", confirmed_at=datetime.now(timezone.utc),
        expected_version=workspace.consent_version, request_key=request_key("consent"),
    ), actor=actor)


def prepare(db, *, actor=None, room="room-1", educational=True, finish=True, with_origin=True):
    actor = actor or user(db)
    patient = Patient(patient_code="SYNTHETIC-" + uuid.uuid4().hex, first_name="Synthetic", last_name="Patient")
    db.add(patient)
    db.commit()
    visit = Visit(patient_id=patient.id, chief_complaint="Synthetic visit", status="open")
    db.add(visit)
    db.commit()
    ReceptionService.save_intake(db, visit.id, ReceptionCreate(
        patient_reported_complaint="Synthetic complaint", assigned_physician_id=actor.id,
        expected_version=0, request_key=request_key("assignment"),
    ), actor=actor)
    audio = grant(db, visit.id, actor, "audio_recording")
    education = grant(db, visit.id, actor, "educational_use") if educational else None
    origin = {"room_code": room, "device_id": identifier(), "client_session_id": identifier()}
    start = RecordingService.start(db, visit.id, RecordingStart(
        recording_id=identifier(), expected_version=0, request_key=request_key("capture"),
        expected_consent_sha256=audio.sha256,
        **({"capture_origin": origin} if with_origin else {}),
    ), actor=actor)
    if finish:
        RecordingService.finish(db, visit.id, RecordingFinish(
            recording_id=start.recording_id, expected_version=1, request_key=request_key("finish"),
            reason="finished", pcm_bytes=32000, encrypted_file_sha256="a" * 64,
        ), actor=actor)
    return {"actor": actor, "visit": visit, "recording_id": start.recording_id,
            "audio": audio, "education": education, "origin": origin}


def packet_data(context, *, text_value=TRANSCRIPT, annotations=True, **changes):
    rows = []
    if annotations:
        for question in QUESTIONS:
            start = text_value.index(question)
            rows.append({"start": start, "end": start + len(question), "text_fa": question,
                         "stage": "initial_visit", "speaker": "clinician"})
    value = {
        "schema_version": "1.0.0", "packet_id": identifier(), "capture_origin": context["origin"],
        "recording_id": context["recording_id"], "source_type": "local_transcript", "source_review_sha256": None,
        "source_text_sha256": sha(text_value), "deidentified_reviewed_text": text_value,
        "question_annotations": rows, "deidentification_reviewed": True, "speaker_attribution_reviewed": True,
        "expected_audio_consent_sha256": context["audio"].sha256,
        "expected_educational_consent_sha256": context["education"].sha256 if context["education"] else "0" * 64,
        "summary_preferences_fa": "شرح‌حال را کوتاه و به ترتیب شروع، عملکرد و اهداف مرور کنید.",
    }
    value.update(changes)
    return value


def submission(context, **changes):
    return VisitLearningSubmit(packet=VisitLearningPacket(**packet_data(context, **changes)),
                               request_key=request_key("packet"), expected_version=0)


def submit(db, context, command=None):
    command = command or submission(context)
    return Service.submit(db, context["visit"].id, command, actor=context["actor"])


def promotion(read, *, bank_version=0, **changes):
    command = dict(expected_version=read.summary.version, expected_packet_sha256=read.summary.packet_sha256,
                   expected_bank_version=bank_version, request_key=request_key("bankdraft"),
                   statement_fa="توالی پرسش‌ها و انتساب گوینده و حذف هویت را برای پیش‌نویس مرور کردم.")
    command.update(changes)
    return VisitLearningPromote(**command)


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def server_review(db, context):
    pcm = b"\x01\x02" * 16000
    physician, visit_id, recording_id = context["actor"], context["visit"].id, context["recording_id"]
    RecordingMediaService.initialize(db, visit_id, recording_id, InitializeAudio(
        request_key=request_key("audio"), pcm_bytes=len(pcm), pcm_sha256=hashlib.sha256(pcm).hexdigest(),
        encrypted_file_sha256="a" * 64,
    ), actor=physician)
    RecordingMediaService.put_chunk(db, visit_id, recording_id, 0, pcm, hashlib.sha256(pcm).hexdigest(), actor=physician)
    RecordingMediaService.complete(db, visit_id, recording_id, CompleteAudio(
        request_key=request_key("complete"), expected_pcm_sha256=hashlib.sha256(pcm).hexdigest(),
    ), actor=physician)
    RecordingMediaService.enqueue(db, visit_id, recording_id, TextCommand(expected_version=1, request_key=request_key("queue")), actor=physician)
    claim = RecordingMediaService.claim(db, visit_id, recording_id)
    RecordingMediaService.finish_job(db, visit_id, recording_id, claim, {
        "text": TRANSCRIPT, "language": "fa", "engine": "faster-whisper", "model_id": "synthetic-only",
        "model_fingerprint": "1" * 64, "segments": [{"start": 0, "end": 0.9, "text": TRANSCRIPT, "speaker": "unknown"}],
        "speaker_identification_verified": False,
    })
    workspace = RecordingMediaService.workspace(db, visit_id, recording_id, actor=physician)
    return RecordingMediaService.review(db, visit_id, recording_id, ReviewText(
        expected_version=workspace.version, request_key=request_key("textreview"),
        expected_draft_sha256=workspace.latest_draft.sha256, edited_text=TRANSCRIPT,
        statement_fa="متن ساختگی ویزیت را به‌صورت مستقل بازبینی و برای آزمون اصلاح کردم.",
    ), actor=physician)


def test_local_text_import_needs_no_audio_upload_and_preserves_exact_sources(db_session):
    context = prepare(db_session)
    command = submission(context)
    before = deepcopy(command.model_dump(mode="json"))
    result = submit(db_session, context, command)
    assert command.model_dump(mode="json") == before
    assert result.packet == command.packet
    assert result.summary.capture_origin.room_code == "room-1"
    assert result.summary.question_count == 2
    assert result.summary.source_type == "local_transcript"
    assert result.summary.status == "submitted"
    assert count(db_session, RecordingAudioTransfer) == 0
    assert not result.model_training_performed
    assert not result.automated_deidentification_guaranteed
    assert not result.automatic_speaker_identification_verified


def test_text_and_review_statement_are_encrypted_and_absent_from_audit_metadata(db_session):
    context = prepare(db_session)
    result = submit(db_session, context)
    row = db_session.scalar(select(VisitLearningEvent))
    assert TRANSCRIPT.encode() not in row.encrypted_data
    assert TRANSCRIPT not in json.dumps(row.payload, ensure_ascii=False)
    assert QUESTIONS[0] not in json.dumps(row.payload, ensure_ascii=False)
    audit = list(db_session.scalars(select(AuditLog).where(AuditLog.entity_type == "visit_learning_events")))
    assert audit and all(QUESTIONS[0] not in json.dumps(item.event_data, ensure_ascii=False) for item in audit)
    assert Service.read(db_session, result.summary.packet_id, actor=context["actor"]).packet.deidentified_reviewed_text == TRANSCRIPT


def test_same_upload_retry_is_idempotent_but_changed_command_is_rejected(db_session):
    context = prepare(db_session)
    command = submission(context)
    first = submit(db_session, context, command)
    assert submit(db_session, context, command).summary.event_sha256 == first.summary.event_sha256
    assert count(db_session, VisitLearningEvent) == 1
    changed = command.model_dump(mode="json")
    changed["packet"]["summary_preferences_fa"] = "ترجیح دیگر برای مرور پزشک"
    with pytest.raises(VisitLearningConflictError):
        submit(db_session, context, VisitLearningSubmit.model_validate(changed))


def test_educational_consent_is_not_inferred_from_audio_consent(db_session):
    context = prepare(db_session, educational=False)
    with pytest.raises(VisitLearningAuthorizationError):
        submit(db_session, context)
    assert count(db_session, VisitLearningEvent) == 0


@pytest.mark.parametrize("purpose", ["audio_recording", "educational_use"])
def test_withdrawal_blocks_read_preview_list_and_promotion_without_destroying_evidence(db_session, purpose):
    context = prepare(db_session)
    result = submit(db_session, context)
    grant(db_session, context["visit"].id, context["actor"], purpose, state="withdrawn")
    for operation in (
        lambda: Service.read(db_session, result.summary.packet_id, actor=context["actor"]),
        lambda: Service.preview_bank(db_session, result.summary.packet_id, actor=context["actor"]),
        lambda: Service.promote_to_bank_draft(db_session, result.summary.packet_id, promotion(result), actor=context["actor"]),
    ):
        with pytest.raises(VisitLearningAuthorizationError):
            operation()
    assert Service.list_for_physician(db_session, actor=context["actor"]) == []
    assert count(db_session, VisitLearningEvent) == 1
    assert count(db_session, PhysicianQuestionEvent) == 0


@pytest.mark.parametrize("purpose", ["audio_recording", "educational_use"])
def test_regrant_does_not_reauthorize_a_packet_bound_to_older_consent(db_session, purpose):
    context = prepare(db_session)
    result = submit(db_session, context)
    grant(db_session, context["visit"].id, context["actor"], purpose, state="withdrawn")
    grant(db_session, context["visit"].id, context["actor"], purpose)
    with pytest.raises(VisitLearningAuthorizationError):
        Service.read(db_session, result.summary.packet_id, actor=context["actor"])


@pytest.mark.parametrize("field", ["expected_audio_consent_sha256", "expected_educational_consent_sha256"])
def test_stale_consent_hash_cannot_be_submitted(db_session, field):
    context = prepare(db_session)
    with pytest.raises((VisitLearningAuthorizationError, VisitLearningConflictError)):
        submit(db_session, context, submission(context, **{field: "0" * 64}))


def test_unfinished_recording_cannot_supply_an_educational_source(db_session):
    context = prepare(db_session, finish=False)
    with pytest.raises(VisitLearningConflictError):
        submit(db_session, context)


def test_packet_cannot_claim_a_different_capture_room_or_device(db_session):
    context = prepare(db_session)
    origin = {**context["origin"], "room_code": "other-room"}
    with pytest.raises(VisitLearningConflictError):
        submit(db_session, context, submission(context, capture_origin=origin))


def test_legacy_recording_without_origin_accepts_explicitly_reported_source_origin(db_session):
    context = prepare(db_session, with_origin=False)
    result = submit(db_session, context)
    assert result.summary.capture_origin_is_client_reported


@pytest.mark.parametrize("role", ["admin", "operator", "nurse", "viewer", "physician"])
def test_another_account_cannot_read_or_promote_the_packet(db_session, role):
    context = prepare(db_session)
    result = submit(db_session, context)
    other = user(db_session, role)
    with pytest.raises((VisitLearningAuthorizationError, VisitLearningNotFoundError)):
        Service.read(db_session, result.summary.packet_id, actor=other)
    with pytest.raises((VisitLearningAuthorizationError, VisitLearningNotFoundError)):
        Service.promote_to_bank_draft(db_session, result.summary.packet_id, promotion(result), actor=other)


def test_reassignment_and_account_deactivation_remove_source_access(db_session):
    context = prepare(db_session)
    result = submit(db_session, context)
    other = user(db_session)
    ReceptionService.save_intake(db_session, context["visit"].id, ReceptionCreate(
        patient_reported_complaint="Synthetic reassignment", assigned_physician_id=other.id,
        expected_version=1, request_key=request_key("reassign"),
    ), actor=context["actor"])
    with pytest.raises(VisitLearningAuthorizationError):
        Service.read(db_session, result.summary.packet_id, actor=context["actor"])
    context["actor"].is_active = False
    db_session.commit()
    with pytest.raises(VisitLearningAuthorizationError):
        Service.list_for_physician(db_session, actor=context["actor"])


def test_central_metadata_filter_keeps_independent_rooms_and_physicians_separate(db_session):
    first = prepare(db_session, room="room-A")
    second = prepare(db_session, actor=first["actor"], room="room-B")
    third = prepare(db_session, room="room-A")
    results = [submit(db_session, item) for item in (first, second, third)]
    metadata = Service.list_for_physician(db_session, actor=first["actor"])
    assert {item.packet_id for item in metadata} == {item.summary.packet_id for item in results[:2]}
    assert all("deidentified_reviewed_text" not in item.model_dump() for item in metadata)
    filtered = Service.list_for_physician(db_session, actor=first["actor"], room_code="room-B")
    assert [item.packet_id for item in filtered] == [results[1].summary.packet_id]
    assert Service.list_for_visit(db_session, first["visit"].id, actor=first["actor"], room_code="room-B") == []


def test_preview_preserves_observed_order_without_inferred_branches_or_activation(db_session):
    context = prepare(db_session)
    result = submit(db_session, context)
    preview = Service.preview_bank(db_session, result.summary.packet_id, actor=context["actor"])
    assert [item.text_fa for item in preview.bank.questions] == list(QUESTIONS)
    assert all(item.depends_on_id is None and item.show_when_answer_in == [] for item in preview.bank.questions)
    assert preview.bank.summary_preferences_fa == result.packet.summary_preferences_fa
    assert not preview.branches_inferred and not preview.activation_performed and not preview.model_training_performed
    assert count(db_session, PhysicianQuestionEvent) == 0
    assert count(db_session, MedicalKnowledgeFact) == 0
    assert count(db_session, ClinicalSafetyRule) == 0


def test_upload_without_annotations_can_be_reviewed_but_cannot_change_the_bank(db_session):
    context = prepare(db_session)
    result = submit(db_session, context, submission(context, annotations=False))
    assert Service.preview_bank(db_session, result.summary.packet_id, actor=context["actor"]).bank is None
    with pytest.raises(VisitLearningConflictError):
        Service.promote_to_bank_draft(db_session, result.summary.packet_id, promotion(result), actor=context["actor"])
    assert count(db_session, PhysicianQuestionEvent) == 0


def test_promotion_only_creates_a_draft_and_leaves_existing_approved_bank_active(db_session):
    context = prepare(db_session)
    actor = context["actor"]
    original = PhysicianQuestionService.save_draft(db_session, actor.id, DraftCreate(
        title_fa="بانک ساختگی قبلی", scope_fa="دامنهٔ ساختگی برای آزمون",
        questions=[{"id": "old.question", "text_fa": "هدف مراجعه چیست؟", "purpose_fa": "مرور هدف مراجعه"}],
        expected_version=0, request_key=request_key("oldbank"),
    ), actor=actor)
    approved = PhysicianQuestionService.review(db_session, actor.id, BankReview(
        expected_version=1, expected_bank_sha256=original.sha256, request_key=request_key("oldapproval"),
        statement_fa="متن و ترتیب بانک ساختگی قبلی را برای آزمون بازبینی کردم.",
    ), actor=actor, action="approve")
    result = submit(db_session, context)
    command = promotion(result, bank_version=2)
    promoted = Service.promote_to_bank_draft(db_session, result.summary.packet_id, command, actor=actor)
    assert promoted.bank_event.action == "draft"
    assert promoted.summary.status == "bank_draft"
    assert not promoted.activation_performed and not promoted.model_training_performed
    workspace = PhysicianQuestionService.workspace(db_session, actor.id, actor=actor)
    assert workspace.active_bank.sha256 == approved.sha256
    assert workspace.latest.sha256 == promoted.bank_event.sha256
    assert Service.promote_to_bank_draft(db_session, result.summary.packet_id, command, actor=actor).bank_event.id == promoted.bank_event.id
    assert count(db_session, VisitLearningEvent) == 2


def test_stale_bank_version_rejects_promotion_without_partial_handoff(db_session):
    context = prepare(db_session)
    result = submit(db_session, context)
    with pytest.raises(VisitLearningConflictError):
        Service.promote_to_bank_draft(db_session, result.summary.packet_id, promotion(result, bank_version=1), actor=context["actor"])
    assert count(db_session, VisitLearningEvent) == 1
    assert count(db_session, PhysicianQuestionEvent) == 0


def test_promotion_requires_the_exact_source_packet_hash(db_session):
    context = prepare(db_session)
    result = submit(db_session, context)
    with pytest.raises(VisitLearningConflictError):
        Service.promote_to_bank_draft(db_session, result.summary.packet_id,
                                     promotion(result, expected_packet_sha256="0" * 64), actor=context["actor"])


def test_reject_is_append_only_and_does_not_train_or_create_questions(db_session):
    context = prepare(db_session)
    result = submit(db_session, context)
    command = VisitLearningReviewCommand(**promotion(result).model_dump(exclude={"expected_bank_version", "title_fa"}))
    rejected = Service.reject(db_session, result.summary.packet_id, command, actor=context["actor"])
    assert rejected.status == "rejected"
    assert Service.reject(db_session, result.summary.packet_id, command, actor=context["actor"]).event_sha256 == rejected.event_sha256
    assert count(db_session, PhysicianQuestionEvent) == 0
    assert count(db_session, VisitLearningEvent) == 2


def test_audit_failure_rolls_back_submission(db_session, monkeypatch):
    context = prepare(db_session)
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic audit failure")
    monkeypatch.setattr(AuditLogRepository, "create", fail)
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        submit(db_session, context)
    assert count(db_session, VisitLearningEvent) == 0


def test_audit_failure_rolls_back_bank_draft_and_learning_event_together(db_session, monkeypatch):
    context = prepare(db_session)
    result = submit(db_session, context)
    original = AuditLogRepository.create
    def fail_learning(db, *args, **kwargs):
        if kwargs.get("entity_type") == "visit_learning_events":
            raise RuntimeError("synthetic handoff audit failure")
        return original(db, *args, **kwargs)
    monkeypatch.setattr(AuditLogRepository, "create", fail_learning)
    with pytest.raises(RuntimeError, match="synthetic handoff audit failure"):
        Service.promote_to_bank_draft(db_session, result.summary.packet_id, promotion(result), actor=context["actor"])
    assert count(db_session, VisitLearningEvent) == 1
    assert count(db_session, PhysicianQuestionEvent) == 0


def test_stored_learning_events_cannot_be_mutated_or_deleted(db_session):
    context = prepare(db_session)
    submit(db_session, context)
    row = db_session.scalar(select(VisitLearningEvent))
    row.action = "reject"
    with pytest.raises(ValueError, match="append-only"):
        db_session.commit()
    db_session.rollback()
    db_session.delete(db_session.get(VisitLearningEvent, row.id))
    with pytest.raises(ValueError, match="append-only"):
        db_session.commit()
    db_session.rollback()


def test_ciphertext_tampering_and_unavailable_key_fail_closed(db_session, monkeypatch):
    context = prepare(db_session)
    result = submit(db_session, context)
    row = db_session.scalar(select(VisitLearningEvent))
    with monkeypatch.context() as unavailable:
        unavailable.setattr(settings, "AUDIO_KEY_ID", "unavailable-version")
        with pytest.raises(AudioConfigurationError):
            Service.read(db_session, result.summary.packet_id, actor=context["actor"])
    db_session.execute(text("UPDATE visit_learning_events SET encrypted_data=:blob WHERE id=:id"), {"blob": b"corrupt", "id": row.id})
    db_session.commit()
    db_session.expire_all()
    with pytest.raises((AudioIntegrityError, VisitLearningConflictError)):
        Service.read(db_session, result.summary.packet_id, actor=context["actor"])


def test_metadata_digest_tampering_is_not_trusted(db_session):
    context = prepare(db_session)
    result = submit(db_session, context)
    row = db_session.scalar(select(VisitLearningEvent))
    db_session.execute(text("UPDATE visit_learning_events SET sha256=:digest WHERE id=:id"), {"digest": "0" * 64, "id": row.id})
    db_session.commit()
    db_session.expire_all()
    with pytest.raises(VisitLearningConflictError):
        Service.read(db_session, result.summary.packet_id, actor=context["actor"])


def test_ciphertext_cannot_be_moved_between_packets_even_with_rewritten_checksums(db_session):
    context = prepare(db_session)
    first = submit(db_session, context)
    second = submit(db_session, context)
    first_row = db_session.scalar(select(VisitLearningEvent).where(
        VisitLearningEvent.packet_id == first.summary.packet_id))
    second_row = db_session.scalar(select(VisitLearningEvent).where(
        VisitLearningEvent.packet_id == second.summary.packet_id))
    transplanted = bytes(second_row.encrypted_data)
    rewritten_metadata = deepcopy(first_row.payload)
    rewritten_metadata["cipher_sha256"] = hashlib.sha256(transplanted).hexdigest()
    # Rewriting a non-secret metadata checksum cannot forge AES-GCM's binding
    # to event/packet/visit/physician identity.
    db_session.execute(text("UPDATE visit_learning_events SET encrypted_data=:blob, payload=:payload, sha256=:digest WHERE id=:id"), {
        "blob": transplanted, "payload": json.dumps(rewritten_metadata, ensure_ascii=False),
        "digest": evidence_digest(rewritten_metadata), "id": first_row.id,
    })
    db_session.commit()
    db_session.expire_all()
    with pytest.raises(AudioIntegrityError):
        Service.read(db_session, first.summary.packet_id, actor=context["actor"])
    assert Service.read(db_session, second.summary.packet_id, actor=context["actor"]).packet.packet_id == second.summary.packet_id


def test_server_source_requires_an_actual_current_physician_review(db_session):
    context = prepare(db_session)
    command = submission(context, source_type="server_reviewed_transcript", source_review_sha256="1" * 64)
    with pytest.raises((VisitLearningConflictError, VisitLearningNotFoundError)):
        submit(db_session, context, command)
    workspace = server_review(db_session, context)
    result = submit(db_session, context, submission(context, source_type="server_reviewed_transcript",
                                                   source_review_sha256=workspace.latest_review.sha256))
    assert result.packet.source_review_sha256 == workspace.latest_review.sha256
    assert not result.model_training_performed


def test_later_server_review_invalidates_stale_learning_source(db_session):
    context = prepare(db_session)
    workspace = server_review(db_session, context)
    result = submit(db_session, context, submission(context, source_type="server_reviewed_transcript",
                                                   source_review_sha256=workspace.latest_review.sha256))
    RecordingMediaService.review(db_session, context["visit"].id, context["recording_id"], ReviewText(
        expected_version=workspace.version, expected_draft_sha256=workspace.latest_draft.sha256,
        edited_text=TRANSCRIPT + "\nاصلاح ساختگی دیگر", request_key=request_key("newreview"),
        statement_fa="این اصلاح ساختگی بعدی را برای بررسی نسخهٔ منبع ثبت کردم.",
    ), actor=context["actor"])
    with pytest.raises(VisitLearningConflictError):
        Service.read(db_session, result.summary.packet_id, actor=context["actor"])


@pytest.mark.parametrize("changes", [
    {"source_text_sha256": "0" * 64},
    {"deidentification_reviewed": False}, {"deidentification_reviewed": 1},
    {"speaker_attribution_reviewed": False}, {"speaker_attribution_reviewed": "true"},
    {"source_type": "local_transcript", "source_review_sha256": "1" * 64},
    {"source_type": "server_reviewed_transcript", "source_review_sha256": None},
    {"question_annotations": [{"start": 0, "end": 4, "text_fa": "ساختگی", "stage": "initial_visit", "speaker": "patient"}]},
    {"question_annotations": [{"start": 0, "end": 4, "text_fa": "ساختگی", "stage": "initial_visit", "speaker": "clinician"}]},
])
def test_malformed_or_unreviewed_packets_are_rejected_before_storage(db_session, changes):
    context = prepare(db_session)
    with pytest.raises(ValidationError):
        VisitLearningPacket(**packet_data(context, **changes))


def test_question_source_offsets_use_unicode_codepoints_not_utf16_units(db_session):
    context = prepare(db_session)
    value = packet_data(context)
    assert value["question_annotations"][0]["start"] == TRANSCRIPT.index(QUESTIONS[0])
    # The leading non-BMP character takes two UTF-16 code units but one Python
    # codepoint. Silently accepting browser-unit offsets would misbind the quote.
    value["question_annotations"][0]["start"] += 1
    value["question_annotations"][0]["end"] += 1
    with pytest.raises(ValidationError):
        VisitLearningPacket(**value)


def terminal_review(db, context, result, action):
    command = promotion(result)
    if action == "bank_draft":
        return Service.promote_to_bank_draft(db, result.summary.packet_id, command, actor=context["actor"])
    return Service.reject(db, result.summary.packet_id, VisitLearningReviewCommand(
        **command.model_dump(exclude={"expected_bank_version", "title_fa"})
    ), actor=context["actor"])


@pytest.mark.parametrize("action", ["bank_draft", "reject"])
def test_terminal_review_ciphertext_is_validated_before_returning_status(db_session, action):
    context = prepare(db_session)
    result = submit(db_session, context)
    terminal_review(db_session, context, result, action)
    terminal = db_session.scalar(select(VisitLearningEvent).where(
        VisitLearningEvent.packet_id == result.summary.packet_id, VisitLearningEvent.version == 2))
    db_session.execute(text("UPDATE visit_learning_events SET encrypted_data=:blob WHERE id=:id"),
                       {"blob": b"corrupted-review", "id": terminal.id})
    db_session.commit()
    db_session.expire_all()
    with pytest.raises(AudioIntegrityError):
        Service.read(db_session, result.summary.packet_id, actor=context["actor"])


def test_terminal_ciphertext_cannot_be_transplanted_with_rewritten_metadata_checksums(db_session):
    context = prepare(db_session)
    first, second = submit(db_session, context), submit(db_session, context)
    for result in (first, second):
        terminal_review(db_session, context, result, "reject")
    first_event = db_session.scalar(select(VisitLearningEvent).where(
        VisitLearningEvent.packet_id == first.summary.packet_id, VisitLearningEvent.version == 2))
    second_event = db_session.scalar(select(VisitLearningEvent).where(
        VisitLearningEvent.packet_id == second.summary.packet_id, VisitLearningEvent.version == 2))
    transplanted = bytes(second_event.encrypted_data)
    body = deepcopy(first_event.payload)
    body["cipher_sha256"] = hashlib.sha256(transplanted).hexdigest()
    db_session.execute(text("UPDATE visit_learning_events SET encrypted_data=:blob, payload=:payload, sha256=:digest WHERE id=:id"), {
        "blob": transplanted, "payload": json.dumps(body, ensure_ascii=False),
        "digest": evidence_digest(body), "id": first_event.id,
    })
    db_session.commit()
    db_session.expire_all()
    with pytest.raises(AudioIntegrityError):
        Service.read(db_session, first.summary.packet_id, actor=context["actor"])
    assert Service.read(db_session, second.summary.packet_id, actor=context["actor"]).summary.status == "rejected"


@pytest.mark.parametrize("field", ["source_text_sha256", "packet_sha256", "source_finish_sha256"])
def test_terminal_source_metadata_must_match_the_authenticated_submission(db_session, field):
    context = prepare(db_session)
    result = submit(db_session, context)
    terminal_review(db_session, context, result, "reject")
    terminal = db_session.scalar(select(VisitLearningEvent).where(
        VisitLearningEvent.packet_id == result.summary.packet_id, VisitLearningEvent.version == 2))
    body = deepcopy(terminal.payload)
    body[field] = "0" * 64
    db_session.execute(text("UPDATE visit_learning_events SET payload=:payload, sha256=:digest WHERE id=:id"), {
        "payload": json.dumps(body, ensure_ascii=False), "digest": evidence_digest(body), "id": terminal.id,
    })
    db_session.commit()
    db_session.expire_all()
    with pytest.raises(VisitLearningConflictError):
        Service.read(db_session, result.summary.packet_id, actor=context["actor"])


def approve_bank(db, actor, draft):
    return PhysicianQuestionService.review(db, actor.id, BankReview(
        expected_version=draft.version, expected_bank_sha256=draft.sha256,
        request_key=request_key("explicit-bank-approval"),
        statement_fa="سؤال‌ها و ترتیب پیش‌نویس ساختگی را جداگانه و صریحاً بررسی و تأیید کردم.",
    ), actor=actor, action="approve")


def test_new_style_reader_rechecks_learning_consent_without_silently_retiring_existing_bank(db_session):
    context = prepare(db_session)
    result = submit(db_session, context)
    promoted = terminal_review(db_session, context, result, "bank_draft")
    approved = approve_bank(db_session, context["actor"], promoted.bank_event)
    assert authorize_approved_bank_source(db_session, approved, actor=context["actor"]) == result.summary.packet_id
    grant(db_session, context["visit"].id, context["actor"], "educational_use", state="withdrawn")
    with pytest.raises(VisitLearningAuthorizationError):
        authorize_approved_bank_source(db_session, approved, actor=context["actor"])
    # Bank activation/retirement retains the existing explicit clinician workflow.
    assert PhysicianQuestionService.workspace(db_session, context["actor"].id,
                                              actor=context["actor"]).active_bank.sha256 == approved.sha256


def test_ordinary_manually_authored_approved_bank_has_no_learning_packet_dependency(db_session):
    actor = user(db_session)
    draft = PhysicianQuestionService.save_draft(db_session, actor.id, DraftCreate(
        title_fa="پرسش‌های دستی ساختگی", scope_fa="تألیف مستقیم پزشک برای آزمون",
        questions=[{"id": "manual.goal", "text_fa": "هدف مراجعه چیست؟", "purpose_fa": "مرور هدف مراجعه"}],
        expected_version=0, request_key=request_key("manual-bank"),
    ), actor=actor)
    approved = approve_bank(db_session, actor, draft)
    assert authorize_approved_bank_source(db_session, approved, actor=actor) is None


def test_revoked_packets_do_not_occupy_central_inbox_pages(db_session):
    oldest = prepare(db_session)
    old_packet = submit(db_session, oldest)
    hidden = prepare(db_session, actor=oldest["actor"])
    submit(db_session, hidden)
    newest = prepare(db_session, actor=oldest["actor"])
    new_packet = submit(db_session, newest)
    grant(db_session, hidden["visit"].id, hidden["actor"], "educational_use", state="withdrawn")
    first_page = Service.list_for_physician(db_session, actor=oldest["actor"], limit=1, offset=0)
    second_page = Service.list_for_physician(db_session, actor=oldest["actor"], limit=1, offset=1)
    assert [item.packet_id for item in first_page] == [new_packet.summary.packet_id]
    assert [item.packet_id for item in second_page] == [old_packet.summary.packet_id]


def test_missing_visit_inbox_uses_the_learning_not_found_boundary(db_session):
    actor = user(db_session)
    with pytest.raises(VisitLearningNotFoundError):
        Service.list_for_visit(db_session, identifier(), actor=actor)


def test_stale_server_review_source_does_not_break_or_fill_other_inbox_pages(db_session):
    local = prepare(db_session)
    local_packet = submit(db_session, local)
    server = prepare(db_session, actor=local["actor"])
    workspace = server_review(db_session, server)
    stale_packet = submit(db_session, server, submission(server, source_type="server_reviewed_transcript",
                                                       source_review_sha256=workspace.latest_review.sha256))
    RecordingMediaService.review(db_session, server["visit"].id, server["recording_id"], ReviewText(
        expected_version=workspace.version, expected_draft_sha256=workspace.latest_draft.sha256,
        edited_text=TRANSCRIPT + "\nاصلاح ساختگی جدید", request_key=request_key("inbox-newreview"),
        statement_fa="متن ساختگی را در بازبینی جدید اصلاح و نسخهٔ منبع را تغییر دادم.",
    ), actor=server["actor"])
    with pytest.raises(VisitLearningConflictError):
        Service.read(db_session, stale_packet.summary.packet_id, actor=server["actor"])
    page = Service.list_for_physician(db_session, actor=local["actor"], limit=1)
    assert [item.packet_id for item in page] == [local_packet.summary.packet_id]
    assert Service.list_for_visit(db_session, server["visit"].id, actor=server["actor"]) == []


def test_reordered_or_overlapping_questions_are_not_inferred_as_valid_sequence(db_session):
    context = prepare(db_session)
    value = packet_data(context)
    value["question_annotations"].reverse()
    with pytest.raises(ValidationError):
        VisitLearningPacket(**value)
    value = packet_data(context)
    value["question_annotations"].append(deepcopy(value["question_annotations"][-1]))
    with pytest.raises(ValidationError):
        VisitLearningPacket(**value)
