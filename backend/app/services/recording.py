"""Consent-bound capture; finish remains possible after consent/assignment changes."""
from datetime import datetime, timezone, timedelta
import uuid
from sqlalchemy import select
from backend.app.db.clinical_record_transactions import clinical_record_write
from backend.app.models.recording import VisitRecordingEvent
from backend.app.models.user import User
from backend.app.models.visit import Visit
from backend.app.models.patient import Patient
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.services.audit_context import actor_data
from backend.app.services.session_finalization import evidence_digest
from backend.app.services.reception import ReceptionService
from backend.app.schemas.recording import RecordingEventRead, RecordingAccess, RecordingCheck

class RecordingNotFoundError(Exception): pass
class RecordingAuthorizationError(Exception): pass
class RecordingConflictError(Exception): pass

def _actor(db, actor):
    current = db.get(User, actor.id)
    if current is None or not current.is_active or current.role != "physician":
        raise RecordingAuthorizationError("Active physician access required.")
    return current

def _visit(db, visit_id):
    visit=db.get(Visit,visit_id)
    if visit is None: raise RecordingNotFoundError("Visit not found.")
    return visit

def _read(row):
    body=row.payload
    if not isinstance(body,dict) or evidence_digest(body)!=row.sha256 or any(body.get(k)!=getattr(row,k) for k in ("id","visit_id","recording_id","version","action","recorded_by","request_key")) or body.get("created_at")!=row.created_at.replace(tzinfo=timezone.utc).isoformat():
        raise RecordingConflictError("Recording history integrity check failed.")
    return RecordingEventRead(**body,sha256=row.sha256)

def _rows(db, visit_id):
    rows=list(db.scalars(select(VisitRecordingEvent).where(VisitRecordingEvent.visit_id==visit_id).order_by(VisitRecordingEvent.version)))
    active=None
    for version,row in enumerate(rows,1):
        _read(row)
        if row.version!=version: raise RecordingConflictError("Recording history is incomplete.")
        if row.action=="start":
            if active: raise RecordingConflictError("Overlapping recording history.")
            active=row
        else:
            if active is None or active.recording_id!=row.recording_id or active.recorded_by!=row.recorded_by:
                raise RecordingConflictError("Recording completion history is inconsistent.")
            active=None
    return rows,active

def _assigned(db,visit_id,actor):
    workspace=ReceptionService.workspace(db,visit_id)
    assigned=workspace.latest_intake.content.get("assigned_physician_id") if workspace.latest_intake else None
    if assigned!=actor.id: raise RecordingAuthorizationError("Only the assigned physician can access recording context.")
    consent=next(c for c in workspace.consents if c.purpose=="audio_recording")
    return consent

def _retry(rows,payload,actor,action):
    for row in rows:
        if row.request_key==payload.request_key:
            if row.recorded_by!=actor.id or row.action!=action or row.payload["command"]!=payload.model_dump(mode="json"):
                raise RecordingConflictError("Request key already used for another command.")
            return _read(row)
    if payload.expected_version!=len(rows): raise RecordingConflictError("Version changed; reload before submitting.")
    return None

def _append(db,visit_id,recording_id,rows,payload,actor,action,consent_id,consent_sha):
    now=datetime.now(timezone.utc)
    body=dict(id=str(uuid.uuid4()),visit_id=visit_id,recording_id=recording_id,version=len(rows)+1,action=action,recorded_by=actor.id,created_at=now.isoformat(),request_key=payload.request_key,command=payload.model_dump(mode="json"),consent_event_id=consent_id,consent_sha256=consent_sha)
    row=VisitRecordingEvent(**{k:body[k] for k in ("id","visit_id","recording_id","version","action","recorded_by","request_key")},created_at=now,payload=body,sha256=evidence_digest(body))
    db.add(row);db.flush()
    AuditLogRepository.create(db,entity_type=row.__tablename__,entity_id=row.id,event_type=action,event_data={"visit_id":visit_id,"recording_id":recording_id,"version":row.version,"sha256":row.sha256},**actor_data(actor),commit=False)
    return _read(row)

class RecordingService:
    @staticmethod
    def access(db,visit_id,*,actor):
        _actor(db,actor);visit=_visit(db,visit_id);consent=_assigned(db,visit_id,actor)
        rows,active=_rows(db,visit_id)
        patient=db.get(Patient,visit.patient_id)
        reason="visit_closed" if visit.status!="open" else "consent_required" if consent.state!="granted" else "session_active" if active else None
        # Never expose another physician's recording details after reassignment.
        return RecordingAccess(visit_id=visit_id,patient_id=visit.patient_id,patient_code=patient.patient_code,physician_id=actor.id,version=len(rows),can_record=reason is None,block_reason=reason,consent_event_id=consent.latest_event.id if consent.latest_event else None,consent_sha256=consent.latest_event.sha256 if consent.latest_event else None,active_recording=_read(active) if active and active.recorded_by==actor.id else None)

    @staticmethod
    @clinical_record_write
    def start(db,visit_id,payload,*,actor):
        _actor(db,actor);_visit(db,visit_id)
        rows,active=_rows(db,visit_id)
        retry=_retry(rows,payload,actor,"start")
        if retry: return retry
        context=RecordingService.access(db,visit_id,actor=actor)
        if not context.can_record or context.consent_sha256!=payload.expected_consent_sha256:
            raise RecordingConflictError("Recording requires the exact current granted consent, an open visit and no active capture.")
        if any(r.recording_id==payload.recording_id for r in rows):
            raise RecordingConflictError("Recording identifier already used.")
        return _append(db,visit_id,payload.recording_id,rows,payload,actor,"start",context.consent_event_id,context.consent_sha256)

    @staticmethod
    def check(db,visit_id,recording_id,*,actor):
        _actor(db,actor);visit=_visit(db,visit_id)
        rows,active=_rows(db,visit_id)
        start=next((r for r in rows if r.recording_id==recording_id and r.action=="start"),None)
        if start is None: raise RecordingNotFoundError("Recording not found.")
        if start.recorded_by!=actor.id: raise RecordingAuthorizationError("Recording belongs to another physician.")
        reason=None
        if active is None or active.id!=start.id: reason="session_changed"
        elif visit.status!="open": reason="visit_closed"
        elif datetime.now(timezone.utc)-start.created_at.replace(tzinfo=timezone.utc)>timedelta(hours=4): reason="duration_limit"
        else:
            try: consent=_assigned(db,visit_id,actor)
            except RecordingAuthorizationError: reason="session_changed"
            else:
                if consent.state!="granted" or consent.latest_event.sha256!=start.payload["consent_sha256"]: reason="consent_changed"
        return RecordingCheck(recording_id=recording_id,can_continue=reason is None,reason=reason,version=len(rows))

    @staticmethod
    @clinical_record_write
    def finish(db,visit_id,payload,*,actor):
        _actor(db,actor);_visit(db,visit_id)
        rows,active=_rows(db,visit_id)
        retry=_retry(rows,payload,actor,"finish")
        if retry: return retry
        if active is None or active.recording_id!=payload.recording_id: raise RecordingConflictError("Capture is not active.")
        if active.recorded_by!=actor.id: raise RecordingAuthorizationError("Only the capturing physician can finish.")
        if payload.pcm_bytes % 2: raise RecordingConflictError("16-bit PCM byte count must be even.")
        if payload.pcm_bytes and not payload.encrypted_file_sha256: raise RecordingConflictError("Nonempty capture requires encrypted file checksum.")
        return _append(db,visit_id,active.recording_id,rows,payload,actor,"finish",active.payload["consent_event_id"],active.payload["consent_sha256"])
