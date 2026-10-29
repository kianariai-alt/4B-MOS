"""Discover currently authorized completed captures without decrypting media.

The query filters ownership, latest assignment and exact original recording
consent before pagination. Existing services recheck evidence integrity and
current authorization before returning each row; transcript reads remain a
separate, freshly authorized operation.
"""
from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from backend.app.models.recording import VisitRecordingEvent
from backend.app.models.recording_media import RecordingAudioTransfer
from backend.app.models.reception import ReceptionRevision, VisitConsentEvent
from backend.app.schemas.capture_origin import CaptureOrigin
from backend.app.schemas.recording_inbox import RecordingInboxItem, RecordingInboxQuery, RecordingInboxRead
from backend.app.services import recording, recording_media


def _authorized_starts(actor_id, room_code):
    start = aliased(VisitRecordingEvent)
    finish = aliased(VisitRecordingEvent)
    latest_intake_version = (
        select(ReceptionRevision.visit_id.label("visit_id"), func.max(ReceptionRevision.version).label("version"))
        .group_by(ReceptionRevision.visit_id).subquery()
    )
    latest_consent_version = (
        select(VisitConsentEvent.visit_id.label("visit_id"), func.max(VisitConsentEvent.version).label("version"))
        .where(VisitConsentEvent.payload["command"]["purpose"].as_string() == "audio_recording")
        .group_by(VisitConsentEvent.visit_id).subquery()
    )
    intake = aliased(ReceptionRevision)
    consent = aliased(VisitConsentEvent)
    query = (
        select(start, finish)
        .join(finish, (finish.visit_id == start.visit_id) & (finish.recording_id == start.recording_id)
              & (finish.action == "finish"))
        .join(latest_intake_version, latest_intake_version.c.visit_id == start.visit_id)
        .join(intake, (intake.visit_id == start.visit_id) & (intake.version == latest_intake_version.c.version))
        .join(latest_consent_version, latest_consent_version.c.visit_id == start.visit_id)
        .join(consent, (consent.visit_id == start.visit_id) & (consent.version == latest_consent_version.c.version))
        .where(start.action == "start", start.recorded_by == actor_id,
               finish.recorded_by == actor_id,
               finish.payload["command"]["reason"].as_string() == "finished",
               intake.payload["command"]["assigned_physician_id"].as_string() == actor_id,
               consent.payload["command"]["state"].as_string() == "granted",
               consent.sha256 == start.payload["consent_sha256"].as_string())
        .order_by(start.created_at.desc(), start.id.desc())
    )
    if room_code is not None:
        query = query.where(start.payload["command"]["capture_origin"]["room_code"].as_string() == room_code)
    return query


def list_recording_inbox(db, *, actor, room_code=None, limit=50, offset=0) -> RecordingInboxRead:
    """Return at most 100 metadata rows; no audio/text decryption or export."""
    recording._actor(db, actor)
    query = RecordingInboxQuery(room_code=room_code, limit=limit, offset=offset)
    candidates = list(db.execute(_authorized_starts(actor.id, query.room_code).offset(query.offset).limit(query.limit + 1)))
    audio_enabled = recording_media.enabled()
    speech_enabled = audio_enabled and recording_media._speech_ready()
    items = []
    for start, finish in candidates[:query.limit]:
        # Recheck the full existing histories, rather than trusting query JSON
        # alone. A concurrent revocation/reassignment suppresses the item.
        try:
            consent = recording._assigned(db, start.visit_id, actor)
        except recording.RecordingAuthorizationError:
            continue
        if consent.state != "granted" or consent.latest_event.sha256 != start.payload["consent_sha256"]:
            continue
        rows, _ = recording._rows(db, start.visit_id)
        matching_start = next((row for row in rows if row.id == start.id), None)
        matching_finish = next((row for row in rows if row.id == finish.id), None)
        if matching_start is None or matching_finish is None:
            raise recording.RecordingConflictError("Recording inbox history changed; reload before selecting a recording.")
        raw_origin = start.payload["command"].get("capture_origin")
        try:
            source = CaptureOrigin.model_validate(raw_origin) if raw_origin is not None else None
        except ValueError:
            raise recording.RecordingConflictError("Recording source metadata is invalid.") from None
        has_transfer = db.scalar(select(RecordingAudioTransfer.id).where(
            RecordingAudioTransfer.visit_id == start.visit_id, RecordingAudioTransfer.recording_id == start.recording_id)) is not None
        media_state, received = "not_uploaded", False
        if has_transfer:
            try:
                media = recording_media.RecordingMediaService.status(db, start.visit_id, start.recording_id, actor=actor)
            except (recording.RecordingAuthorizationError, recording_media.MediaAuthorizationError):
                continue
            media_state, received = media.state, media.audio_received
        items.append(RecordingInboxItem(
            visit_id=start.visit_id, recording_id=start.recording_id,
            captured_at=recording._utc(start.created_at), finished_at=recording._utc(finish.created_at),
            capture_origin=source, origin_missing_for_legacy=source is None,
            media_state=media_state, audio_received=received,
        ))
    return RecordingInboxRead(
        items=tuple(items), next_offset=query.offset + query.limit if len(candidates) > query.limit else None,
        audio_upload_enabled=audio_enabled, transcription_enabled=speech_enabled,
    )
