"""Consent-bound encrypted interview examples and explicit bank-draft handoff.

This stores human-reviewed examples, not model weights or approved medical
knowledge. Account locks precede visit locks; bank drafts and source events share
one commit so audit failures cannot leave a half-promoted proposal.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from types import SimpleNamespace
import uuid

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import aliased

from backend.app.core.config import settings
from backend.app.db.account_transactions import atomic_account_write
from backend.app.db.clinical_record_transactions import _lock_visit
from backend.app.models.physician_questions import PhysicianQuestionEvent
from backend.app.models.reception import VisitConsentEvent
from backend.app.models.recording_media import RecordingAudioTransfer, RecordingTextEvent
from backend.app.models.visit_learning import VisitLearningEvent
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.schemas.capture_origin import CaptureOrigin
from backend.app.schemas.physician_questions import BankContent, DraftCreate, InterviewQuestion
from backend.app.schemas.visit_learning import (
    VisitLearningBankPreview, VisitLearningPacket, VisitLearningPromote,
    VisitLearningPromotion, VisitLearningRead, VisitLearningReviewCommand,
    VisitLearningSubmit, VisitLearningSummary,
)
from backend.app.services import recording
from backend.app.services.audio_crypto import AudioIntegrityError, decrypt, digest, encrypt, key
from backend.app.services.audit_context import actor_data
from backend.app.services.physician_questions import PhysicianQuestionService, QuestionBankConflictError, _read as read_bank_event
from backend.app.services.recording_media import RecordingMediaService, MediaAuthorizationError, MediaConflictError, MediaNotFoundError
from backend.app.services.recording_inbox import _authorized_starts
from backend.app.services.reception import ReceptionConflictError, ReceptionNotFoundError, ReceptionService
from backend.app.services.session_finalization import evidence_digest


class VisitLearningNotFoundError(Exception):
    pass


class VisitLearningAuthorizationError(Exception):
    pass


class VisitLearningConflictError(Exception):
    pass


META_FIELDS = (
    "id", "packet_id", "visit_id", "physician_id", "recording_id", "room_code",
    "device_id", "client_session_id", "source_type", "version", "action",
    "request_key", "recorded_by", "bank_event_id", "key_id",
)
SOURCE_FIELDS = (
    "recording_id", "source_type", "source_review_sha256",
    "expected_audio_consent_sha256", "expected_educational_consent_sha256",
)


def _actor(db, actor):
    try:
        return recording._actor(db, actor)
    except recording.RecordingAuthorizationError as error:
        raise VisitLearningAuthorizationError(str(error)) from error


def _time(value):
    return recording._utc(value).isoformat()


def _verify(row):
    body = row.payload
    if (not isinstance(body, dict) or evidence_digest(body) != row.sha256
            or any(body.get(name) != getattr(row, name) for name in META_FIELDS)
            or body.get("created_at") != _time(row.created_at)
            or not {"command_sha256", "packet_sha256", "source_text_sha256", "question_count", "source_review_sha256",
                    "expected_audio_consent_sha256", "expected_educational_consent_sha256", "cipher_sha256",
                    "cipher_context", "previous_event_sha256", "source_start_sha256", "source_finish_sha256"} <= body.keys()):
        raise VisitLearningConflictError("Interview-learning metadata integrity failed.")
    return body


def _rows(db, packet_id):
    rows = list(db.scalars(select(VisitLearningEvent).where(
        VisitLearningEvent.packet_id == packet_id).order_by(VisitLearningEvent.version)))
    previous = None
    for version, row in enumerate(rows, 1):
        body = _verify(row)
        if row.version != version or body.get("previous_event_sha256") != previous:
            raise VisitLearningConflictError("Interview-learning event history is incomplete.")
        if version == 1 and row.action != "submit" or version > 1 and row.action == "submit":
            raise VisitLearningConflictError("Interview-learning submission history is invalid.")
        if version > 2:
            raise VisitLearningConflictError("A learning packet has more than one terminal decision.")
        if rows and any(getattr(row, name) != getattr(rows[0], name) for name in (
            "visit_id", "physician_id", "recording_id", "room_code", "device_id", "client_session_id", "source_type")):
            raise VisitLearningConflictError("Interview-learning source identity changed across events.")
        previous = row.sha256
    return rows


def _source_authorize(db, visit_id, source, actor):
    """Check purpose-specific current consent before decrypting source text."""
    current = _actor(db, actor)
    try:
        recording._visit(db, visit_id)
        workspace = ReceptionService.workspace(db, visit_id)
        assigned = workspace.latest_intake.content.get("assigned_physician_id") if workspace.latest_intake else None
        if assigned != current.id:
            raise VisitLearningAuthorizationError("Only the currently assigned physician can access a learning packet.")
        consents = {item.purpose: item for item in workspace.consents}
        for purpose, expected in (
            ("audio_recording", source.expected_audio_consent_sha256),
            ("educational_use", source.expected_educational_consent_sha256),
        ):
            consent = consents[purpose]
            if consent.state != "granted" or consent.latest_event is None or consent.latest_event.sha256 != expected:
                raise VisitLearningAuthorizationError("Current granted audio and educational consent with exact hashes is required.")
        history, _ = recording._rows(db, visit_id)
        start = next((row for row in history if row.recording_id == source.recording_id and row.action == "start"), None)
        finish = next((row for row in history if row.recording_id == source.recording_id and row.action == "finish"), None)
        if start is None:
            raise VisitLearningNotFoundError("The source recording was not found.")
        if start.recorded_by != current.id:
            raise VisitLearningAuthorizationError("The learning source belongs to another recording physician.")
        if finish is None or finish.payload["command"]["reason"] != "finished":
            raise VisitLearningConflictError("A normally completed source recording is required.")
        if start.payload["consent_sha256"] != source.expected_audio_consent_sha256:
            raise VisitLearningAuthorizationError("The source recording's original audio consent is no longer current.")
        recorded_origin = start.payload["command"].get("capture_origin")
        if recorded_origin is not None and CaptureOrigin.model_validate(recorded_origin) != source.capture_origin:
            raise VisitLearningConflictError("Learning capture origin does not match its recording receipt.")
        if source.source_type == "server_reviewed_transcript":
            media = RecordingMediaService.workspace(db, visit_id, source.recording_id, actor=current)
            if media.latest_review is None or media.latest_review.sha256 != source.source_review_sha256:
                raise VisitLearningConflictError("The exact latest server transcript review is required.")
        return start, finish
    except (recording.RecordingAuthorizationError, MediaAuthorizationError) as error:
        raise VisitLearningAuthorizationError(str(error)) from error
    except (recording.RecordingNotFoundError, ReceptionNotFoundError, MediaNotFoundError) as error:
        raise VisitLearningNotFoundError(str(error)) from error
    except (recording.RecordingConflictError, ReceptionConflictError, MediaConflictError) as error:
        raise VisitLearningConflictError(str(error)) from error


def _summary(root, event):
    return VisitLearningSummary(
        packet_id=root.packet_id, visit_id=root.visit_id, recording_id=root.recording_id,
        physician_id=root.physician_id,
        capture_origin=CaptureOrigin(room_code=root.room_code, device_id=root.device_id, client_session_id=root.client_session_id),
        source_type=root.source_type, version=event.version,
        status={"submit": "submitted", "bank_draft": "bank_draft", "reject": "rejected"}[event.action],
        packet_sha256=root.payload["packet_sha256"], event_sha256=event.sha256,
        question_count=root.payload["question_count"], created_at=_time(root.created_at),
        bank_event_id=event.bank_event_id,
    )


def _read_authorized(db, packet_id, actor):
    current = _actor(db, actor)
    key()
    rows = _rows(db, packet_id)
    if not rows or rows[0].physician_id != current.id:
        raise VisitLearningNotFoundError("Learning packet not found for this physician.")
    root = rows[0]
    body = root.payload
    source = SimpleNamespace(**{name: body[name] for name in SOURCE_FIELDS},
                             capture_origin=CaptureOrigin(room_code=root.room_code, device_id=root.device_id, client_session_id=root.client_session_id))
    start, finish = _source_authorize(db, root.visit_id, source, current)
    if body.get("source_start_sha256") != start.sha256 or body.get("source_finish_sha256") != finish.sha256:
        raise VisitLearningConflictError("Recording source receipts no longer match the learning packet.")
    try:
        packet = VisitLearningPacket.model_validate(_decrypt_event(root))
    except (ValueError, TypeError, KeyError) as error:
        raise VisitLearningConflictError("The encrypted learning packet is not a valid supported packet.") from error
    if (evidence_digest(packet.model_dump(mode="json")) != body["packet_sha256"] or packet.packet_id != packet_id
            or any(getattr(packet, name) != body[name] for name in SOURCE_FIELDS)
            or packet.capture_origin != source.capture_origin or len(packet.question_annotations) != body["question_count"]
            or packet.source_text_sha256 != body["source_text_sha256"] or root.bank_event_id is not None):
        raise VisitLearningConflictError("The decrypted learning packet conflicts with its immutable metadata.")
    for terminal in rows[1:]:
        _validate_terminal(db, root, terminal, packet)
    return rows, packet


def _decrypt_event(row):
    """Check each encrypted source/review event, including terminal decisions."""
    body = row.payload
    if row.encrypted_data is None or digest(row.encrypted_data) != body.get("cipher_sha256"):
        raise AudioIntegrityError("Encrypted learning-event checksum failed.")
    context = {"event_id": row.id, "packet_id": row.packet_id, "visit_id": row.visit_id,
               "physician_id": row.physician_id, "version": row.version,
               "purpose": "visit-learning-" + row.action + "-v1"}
    if body.get("cipher_context") != context:
        raise AudioIntegrityError("Learning-event ciphertext context failed.")
    try:
        content = json.loads(decrypt(row.encrypted_data, context, row.key_id))
    except (ValueError, TypeError) as error:
        raise VisitLearningConflictError("The encrypted learning event is not supported JSON.") from error
    if not isinstance(content, dict):
        raise VisitLearningConflictError("The encrypted learning event must be an object.")
    return content


def _retry(db, physician_id, packet_id, command, action):
    row = db.scalar(select(VisitLearningEvent).where(
        VisitLearningEvent.physician_id == physician_id,
        VisitLearningEvent.request_key == command.request_key))
    if row is None:
        return None
    _verify(row)
    if row.packet_id != packet_id or row.action != action or row.payload["command_sha256"] != evidence_digest(command.model_dump(mode="json")):
        raise VisitLearningConflictError("Learning request key was already used for a different command.")
    return row


def _append(db, visit_id, packet, rows, action, command, actor, *, content, source_receipts=None, bank_event=None):
    identifier = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    version = len(rows) + 1
    context = {"event_id": identifier, "packet_id": packet.packet_id, "visit_id": visit_id,
               "physician_id": actor.id, "version": version, "purpose": "visit-learning-" + action + "-v1"}
    encrypted_content = content if action == "submit" else {**content, "command": command.model_dump(mode="json")}
    blob = encrypt(json.dumps(encrypted_content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"), context, settings.AUDIO_KEY_ID)
    body = dict(
        id=identifier, packet_id=packet.packet_id, visit_id=visit_id, physician_id=actor.id,
        recording_id=packet.recording_id, **packet.capture_origin.model_dump(mode="json"),
        source_type=packet.source_type, version=version, action=action, request_key=command.request_key,
        recorded_by=actor.id, bank_event_id=bank_event.id if bank_event else None,
        key_id=settings.AUDIO_KEY_ID, created_at=now.isoformat(),
        command_sha256=evidence_digest(command.model_dump(mode="json")),
        packet_sha256=evidence_digest(packet.model_dump(mode="json")),
        source_text_sha256=packet.source_text_sha256, question_count=len(packet.question_annotations),
        source_review_sha256=packet.source_review_sha256,
        expected_audio_consent_sha256=packet.expected_audio_consent_sha256,
        expected_educational_consent_sha256=packet.expected_educational_consent_sha256,
        previous_event_sha256=rows[-1].sha256 if rows else None,
        cipher_context=context, cipher_sha256=digest(blob),
        bank_event_sha256=bank_event.sha256 if bank_event else None,
        source_start_sha256=source_receipts[0].sha256 if source_receipts else rows[0].payload["source_start_sha256"],
        source_finish_sha256=source_receipts[1].sha256 if source_receipts else rows[0].payload["source_finish_sha256"],
    )
    row = VisitLearningEvent(**{name: body[name] for name in META_FIELDS}, created_at=now,
                             encrypted_data=blob, payload=body, sha256=evidence_digest(body))
    db.add(row)
    db.flush()
    AuditLogRepository.create(db, entity_type=row.__tablename__, entity_id=row.id,
        event_type="visit_learning_" + action,
        event_data={"packet_id": row.packet_id, "version": row.version, "sha256": row.sha256,
                    "bank_event_id": row.bank_event_id}, **actor_data(actor), commit=False)
    return row


def _proposed_bank(packet, title=None):
    if not packet.question_annotations:
        return None
    stage_labels = {"reception": "پذیرش", "initial_visit": "ویزیت اولیه", "physician_visit": "ویزیت پزشک"}
    return BankContent(
        title_fa=title or "پیش‌نویس پرسش‌های ویزیت برای بازبینی پزشک",
        scope_fa="پیشنهاد حاصل از نمونهٔ انسانیِ بی‌هویت و بازبینی‌شده؛ نیازمند بررسی و تأیید جداگانه. منبع: " + packet.packet_id,
        summary_preferences_fa=packet.summary_preferences_fa,
        questions=[InterviewQuestion(
            id="learn." + packet.packet_id + "." + str(index), text_fa=item.text_fa,
            purpose_fa="سؤال مشاهده‌شده در " + stage_labels[item.stage] + "؛ هش متن منبع " + packet.source_text_sha256
                       + "؛ شرط و گزینه از گفتگوی منفرد استنباط نشده است.",
            answer_type="text",
        ) for index, item in enumerate(packet.question_annotations, 1)],
    )


def _validate_terminal(db, root, event, packet):
    """Bind review status and draft provenance to the encrypted review command."""
    body = event.payload
    source_fields = (*SOURCE_FIELDS, "packet_sha256", "source_text_sha256", "question_count",
                     "source_start_sha256", "source_finish_sha256")
    if any(body.get(name) != root.payload.get(name) for name in source_fields):
        raise VisitLearningConflictError("Learning-review source metadata differs from its submission.")
    content = _decrypt_event(event)
    command_type = VisitLearningPromote if event.action == "bank_draft" else VisitLearningReviewCommand
    try:
        command = command_type.model_validate(content.get("command"))
    except (ValueError, TypeError) as error:
        raise VisitLearningConflictError("The encrypted learning-review command is invalid.") from error
    if (evidence_digest(command.model_dump(mode="json")) != body["command_sha256"]
            or command.request_key != event.request_key or command.expected_version != event.version - 1
            or command.expected_packet_sha256 != root.payload["packet_sha256"]
            or content.get("statement_fa") != command.statement_fa):
        raise VisitLearningConflictError("The learning review does not match its encrypted command.")
    if event.action == "reject":
        if event.bank_event_id is not None or body.get("bank_event_sha256") is not None:
            raise VisitLearningConflictError("A rejected learning packet cannot link a question-bank draft.")
        return
    bank_row = db.get(PhysicianQuestionEvent, event.bank_event_id) if event.bank_event_id else None
    if bank_row is None or bank_row.sha256 != body.get("bank_event_sha256"):
        raise VisitLearningConflictError("The linked question-bank draft is missing or changed.")
    try:
        bank = read_bank_event(bank_row)
    except QuestionBankConflictError as error:
        raise VisitLearningConflictError(str(error)) from error
    expected_bank = _proposed_bank(packet, command.title_fa)
    if (expected_bank is None or bank.action != "draft" or bank.physician_id != root.physician_id
            or bank.recorded_by != event.recorded_by or bank.content != expected_bank
            or bank.version != command.expected_bank_version + 1
            or bank.command.get("expected_version") != command.expected_bank_version):
        raise VisitLearningConflictError("The question-bank draft differs from its reviewed source proposal.")


def _expected(rows, payload):
    if payload.expected_version != len(rows) or payload.expected_packet_sha256 != rows[0].payload["packet_sha256"]:
        raise VisitLearningConflictError("Learning packet version or source-content hash changed; reload before review.")
    if rows[-1].action != "submit":
        raise VisitLearningConflictError("Only a submitted learning packet can receive a terminal review.")


def _bounds(room_code, limit, offset):
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or not 0 <= offset <= 10000:
        raise ValueError("Learning list limits are out of range.")
    if room_code is not None and (type(room_code) is not str or re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", room_code) is None):
        raise ValueError("Invalid room code.")


def _visible_submissions(actor_id, room_code=None, visit_id=None):
    """Apply current assignment and both consent purposes before pagination."""
    captures = _authorized_starts(actor_id, None).order_by(None).subquery()
    education_versions = (
        select(VisitConsentEvent.visit_id.label("visit_id"), func.max(VisitConsentEvent.version).label("version"))
        .where(VisitConsentEvent.payload["command"]["purpose"].as_string() == "educational_use")
        .group_by(VisitConsentEvent.visit_id).subquery()
    )
    education = aliased(VisitConsentEvent)
    review = aliased(RecordingTextEvent)
    later_review = aliased(RecordingTextEvent)
    current_review = exists(select(review.id).join(
        RecordingAudioTransfer, review.transfer_id == RecordingAudioTransfer.id,
    ).where(
        RecordingAudioTransfer.visit_id == VisitLearningEvent.visit_id,
        RecordingAudioTransfer.recording_id == VisitLearningEvent.recording_id,
        review.action == "review",
        review.sha256 == VisitLearningEvent.payload["source_review_sha256"].as_string(),
        ~exists(select(later_review.id).where(
            later_review.transfer_id == review.transfer_id, later_review.action == "review",
            later_review.version > review.version,
        )),
    ))
    query = (select(VisitLearningEvent)
        .join(captures, (captures.c.visit_id == VisitLearningEvent.visit_id)
              & (captures.c.recording_id == VisitLearningEvent.recording_id))
        .join(education_versions, education_versions.c.visit_id == VisitLearningEvent.visit_id)
        .join(education, (education.visit_id == education_versions.c.visit_id)
              & (education.version == education_versions.c.version))
        .where(VisitLearningEvent.physician_id == actor_id, VisitLearningEvent.action == "submit",
               education.payload["command"]["state"].as_string() == "granted",
               education.sha256 == VisitLearningEvent.payload["expected_educational_consent_sha256"].as_string(),
               captures.c.payload["consent_sha256"].as_string()
               == VisitLearningEvent.payload["expected_audio_consent_sha256"].as_string(),
               or_(VisitLearningEvent.source_type == "local_transcript", current_review)))
    if room_code is not None:
        query = query.where(VisitLearningEvent.room_code == room_code)
    if visit_id is not None:
        query = query.where(VisitLearningEvent.visit_id == visit_id)
    return query.order_by(VisitLearningEvent.created_at.desc(), VisitLearningEvent.id)


def authorize_approved_bank_source(db, approved_bank, *, actor):
    """Recheck a directly linked learning source for the new style reader.

    Ordinary manually authored banks have no learning-source link. This does
    not retire a bank or claim to discover provenance removed by manual copying.
    """
    current = _actor(db, actor)
    if approved_bank.physician_id != current.id or approved_bank.action != "approve":
        raise VisitLearningAuthorizationError("An approved bank owned by the current physician is required.")
    linked = list(db.scalars(select(VisitLearningEvent).join(
        PhysicianQuestionEvent, VisitLearningEvent.bank_event_id == PhysicianQuestionEvent.id,
    ).where(
        VisitLearningEvent.physician_id == current.id,
        VisitLearningEvent.action == "bank_draft",
        PhysicianQuestionEvent.sha256 == approved_bank.reviewed_bank_sha256,
    )))
    if not linked:
        return None
    if len(linked) != 1:
        raise VisitLearningConflictError("The approved bank has ambiguous learning-source provenance.")
    rows, _ = _read_authorized(db, linked[0].packet_id, current)
    if rows[-1].id != linked[0].id or rows[-1].action != "bank_draft":
        raise VisitLearningConflictError("The approved bank learning-source link is inconsistent.")
    return rows[0].packet_id


class VisitLearningService:
    @staticmethod
    @atomic_account_write
    def submit(db, visit_id, payload: VisitLearningSubmit, *, actor):
        payload = VisitLearningSubmit.model_validate(payload.model_dump(mode="json"))
        _lock_visit(db, {"visit_id": visit_id})
        current = _actor(db, actor)
        key()
        packet = payload.packet
        receipts = _source_authorize(db, visit_id, packet, current)
        existing = _retry(db, current.id, packet.packet_id, payload, "submit")
        if existing is not None:
            rows, stored = _read_authorized(db, packet.packet_id, current)
            return VisitLearningRead(summary=_summary(rows[0], existing), packet=stored)
        if _rows(db, packet.packet_id):
            raise VisitLearningConflictError("Learning packet identifier already exists; use its original request key.")
        row = _append(db, visit_id, packet, [], "submit", payload, current,
                      content=packet.model_dump(mode="json"), source_receipts=receipts)
        return VisitLearningRead(summary=_summary(row, row), packet=packet)

    @staticmethod
    def read(db, packet_id, *, actor):
        rows, packet = _read_authorized(db, packet_id, actor)
        return VisitLearningRead(summary=_summary(rows[0], rows[-1]), packet=packet)

    @staticmethod
    def list_for_physician(db, *, actor, room_code=None, limit=50, offset=0):
        current = _actor(db, actor)
        key()
        _bounds(room_code, limit, offset)
        roots = list(db.scalars(_visible_submissions(current.id, room_code).offset(offset).limit(limit)))
        result = []
        for root in roots:
            try:
                result.append(VisitLearningService.read(db, root.packet_id, actor=current).summary)
            except (VisitLearningAuthorizationError, VisitLearningNotFoundError):
                # A withdrawal/reassignment revokes inbox visibility as well as
                # read/download. Integrity failures remain explicit failures.
                continue
        return result

    @staticmethod
    def list_for_visit(db, visit_id, *, actor, room_code=None, limit=50, offset=0):
        current = _actor(db, actor)
        try:
            workspace = ReceptionService.workspace(db, visit_id)
        except ReceptionNotFoundError as error:
            raise VisitLearningNotFoundError(str(error)) from error
        except ReceptionConflictError as error:
            raise VisitLearningConflictError(str(error)) from error
        if workspace.latest_intake is None or workspace.latest_intake.content.get("assigned_physician_id") != current.id:
            raise VisitLearningAuthorizationError("Only the assigned physician can read a visit's learning packets.")
        # Keep pagination specific to this visit rather than filtering a page
        # of unrelated rooms/visits after the fact.
        key()
        _bounds(room_code, limit, offset)
        roots = list(db.scalars(_visible_submissions(current.id, room_code, visit_id).offset(offset).limit(limit)))
        result = []
        for root in roots:
            try:
                result.append(VisitLearningService.read(db, root.packet_id, actor=current).summary)
            except (VisitLearningAuthorizationError, VisitLearningNotFoundError):
                continue
        return result

    @staticmethod
    def preview_bank(db, packet_id, *, actor):
        reviewed = VisitLearningService.read(db, packet_id, actor=actor)
        bank = _proposed_bank(reviewed.packet) if reviewed.summary.status == "submitted" else None
        return VisitLearningBankPreview(summary=reviewed.summary, bank=bank, review_requirements_fa=(
            "هویت‌زدایی و انتساب گوینده، گواهی انسانی هستند و تضمین خودکار نیستند؛ متن و سؤال‌ها دوباره بررسی شوند.",
            "ترتیب فقط ترتیب سؤال‌های حاشیه‌نویسی‌شده است؛ شاخه، گزینه و معیار تشخیصی از یک ویزیت استنباط نشده‌اند.",
            "این پیشنهاد تنها می‌تواند Draft بانک پزشک شود؛ فعال‌سازی، تأیید جداگانهٔ همان نسخه و هش را لازم دارد.",
        ))

    @staticmethod
    @atomic_account_write
    def promote_to_bank_draft(db, packet_id, payload: VisitLearningPromote, *, actor):
        payload = VisitLearningPromote.model_validate(payload.model_dump(mode="json"))
        # Read source identity before the visit lock; account authorization is
        # serialized already and the immutable row is revalidated after lock.
        source = db.scalar(select(VisitLearningEvent).where(VisitLearningEvent.packet_id == packet_id,
                            VisitLearningEvent.action == "submit"))
        if source is None:
            raise VisitLearningNotFoundError("Learning packet not found.")
        _lock_visit(db, {"visit_id": source.visit_id})
        rows, packet = _read_authorized(db, packet_id, actor)
        retry = _retry(db, actor.id, packet_id, payload, "bank_draft")
        if retry is not None:
            bank_row = db.get(PhysicianQuestionEvent, retry.bank_event_id)
            if bank_row is None or bank_row.sha256 != retry.payload["bank_event_sha256"]:
                raise VisitLearningConflictError("The linked question-bank draft is missing or changed.")
            try:
                checked_bank = read_bank_event(bank_row)
            except QuestionBankConflictError as error:
                raise VisitLearningConflictError(str(error)) from error
            return VisitLearningPromotion(summary=_summary(rows[0], retry), bank_event=checked_bank)
        _expected(rows, payload)
        bank = _proposed_bank(packet, payload.title_fa)
        if bank is None:
            raise VisitLearningConflictError("At least one reviewed clinician-question annotation is required for a bank draft.")
        draft = DraftCreate(**bank.model_dump(mode="json"), expected_version=payload.expected_bank_version,
                            request_key="learning-" + evidence_digest({"packet_id": packet_id, "request_key": payload.request_key}))
        try:
            bank_event = PhysicianQuestionService._save_draft_in_transaction(db, actor.id, draft, actor=actor)
        except QuestionBankConflictError as error:
            raise VisitLearningConflictError(str(error)) from error
        row = _append(db, rows[0].visit_id, packet, rows, "bank_draft", payload, actor,
                      content={"statement_fa": payload.statement_fa}, bank_event=bank_event)
        return VisitLearningPromotion(summary=_summary(rows[0], row), bank_event=bank_event)

    @staticmethod
    @atomic_account_write
    def reject(db, packet_id, payload: VisitLearningReviewCommand, *, actor):
        payload = VisitLearningReviewCommand.model_validate(payload.model_dump(mode="json"))
        source = db.scalar(select(VisitLearningEvent).where(VisitLearningEvent.packet_id == packet_id,
                            VisitLearningEvent.action == "submit"))
        if source is None:
            raise VisitLearningNotFoundError("Learning packet not found.")
        _lock_visit(db, {"visit_id": source.visit_id})
        rows, packet = _read_authorized(db, packet_id, actor)
        retry = _retry(db, actor.id, packet_id, payload, "reject")
        if retry is not None:
            return _summary(rows[0], retry)
        _expected(rows, payload)
        row = _append(db, rows[0].visit_id, packet, rows, "reject", payload, actor,
                      content={"statement_fa": payload.statement_fa})
        return _summary(rows[0], row)
