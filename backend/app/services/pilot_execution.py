"""Bounded controlled-pilot execution; no automatic individual clinical clearance."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.pilot_execution import PilotStopEvent, PilotVisitEnrollment
from backend.app.models.treatment import Treatment
from backend.app.models.pilot_release import PilotReleaseDecision
from backend.app.models.treatment_outcome import TreatmentOutcome
from backend.app.models.user import User
from backend.app.models.visit import Visit
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.repositories.pilot_release import PilotReleaseDecisionRepository
from backend.app.repositories.protocol import ProtocolRepository
from backend.app.repositories.treatment import TreatmentRepository
from backend.app.repositories.visit import VisitRepository
from backend.app.schemas.pilot_execution import (
    PilotAcceptanceRead, PilotEnrollmentCreate, PilotEnrollmentRead,
    PilotOperationsRead, PilotStopCreate, PilotStopRead,
)
from backend.app.schemas.protocol import ProtocolRead
from backend.app.services.audit_context import actor_data
from backend.app.services.pilot_authorization import (
    PilotReleaseDecisionIntegrityError, PilotReleaseDecisionService, _as_utc,
    _same_timestamp,
)
from backend.app.services.pilot_launch import PilotLaunchPackageService
from backend.app.services.session_finalization import evidence_digest
from backend.app.services.treatment_decision import (
    TreatmentDecisionIntegrityError, TreatmentDecisionService,
)


class PilotExecutionNotFoundError(Exception):
    pass


class PilotExecutionConflictError(Exception):
    pass


class PilotExecutionAuthorizationError(Exception):
    pass


class PilotExecutionIntegrityError(Exception):
    pass


def _to_utc(value: datetime) -> datetime:
    return _as_utc(value)


class PilotExecutionService:
    @staticmethod
    def _release(db: Session, decision_id: str, *, lock: bool = False) -> PilotReleaseDecision:
        stmt = select(PilotReleaseDecision).where(PilotReleaseDecision.id == decision_id)
        if lock:
            stmt = stmt.with_for_update()
        row = db.scalar(stmt.execution_options(populate_existing=True))
        if row is None:
            raise PilotExecutionNotFoundError("The pilot release decision was not found.")
        try:
            PilotReleaseDecisionService._validate(row)
            package = PilotLaunchPackageService.get(db, row.package_id)
        except Exception as error:
            raise PilotExecutionIntegrityError(
                "The pilot release or launch package failed its integrity check."
            ) from error
        if package.sha256 != row.package_sha256:
            raise PilotExecutionIntegrityError(
                "The pilot release no longer matches its immutable launch package."
            )
        return row

    @staticmethod
    def _enrollment(record: PilotVisitEnrollment) -> PilotEnrollmentRead:
        raw = deepcopy(record.payload)
        valid = (
            isinstance(raw, dict)
            and evidence_digest(raw) == record.sha256
            and raw.get("schema_version") == 1
            and raw.get("id") == record.id
            and raw.get("visit_id") == record.visit_id
            and raw.get("release_decision_id") == record.release_decision_id
            and raw.get("release_decision_sha256") == record.release_decision_sha256
            and raw.get("protocol_template_id") == record.protocol_template_id
            and raw.get("protocol_snapshot_sha256") == record.protocol_snapshot_sha256
            and raw.get("clinician_decision_id") == record.clinician_decision_id
            and raw.get("clinician_decision_sha256") == record.clinician_decision_sha256
            and raw.get("consent_evidence_reference") == record.consent_evidence_reference
            and _same_timestamp(raw.get("consent_confirmed_at"), record.consent_confirmed_at)
            and raw.get("clinician_statement") == record.clinician_statement
            and raw.get("enrolled_by_user_id") == record.enrolled_by_user_id
            and _same_timestamp(raw.get("created_at"), record.created_at)
            and raw.get("authorizes_individual_treatment") is False
            and raw.get("confirms_patient_consent_document_authenticity") is False
        )
        if not valid:
            raise PilotExecutionIntegrityError("Pilot enrollment failed its integrity check.")
        return PilotEnrollmentRead(
            id=record.id, release_decision_id=record.release_decision_id,
            release_decision_sha256=record.release_decision_sha256,
            visit_id=record.visit_id, protocol_template_id=record.protocol_template_id,
            protocol_snapshot_sha256=record.protocol_snapshot_sha256,
            clinician_decision_id=record.clinician_decision_id,
            clinician_decision_sha256=record.clinician_decision_sha256,
            consent_evidence_reference=record.consent_evidence_reference,
            consent_confirmed_at=record.consent_confirmed_at,
            clinician_statement=record.clinician_statement,
            enrolled_by_user_id=record.enrolled_by_user_id,
            sha256=record.sha256, created_at=record.created_at,
        )

    @staticmethod
    def _stop(record: PilotStopEvent) -> PilotStopRead:
        raw = deepcopy(record.payload)
        valid = (
            isinstance(raw, dict)
            and evidence_digest(raw) == record.sha256
            and raw.get("schema_version") == 1
            and raw.get("id") == record.id
            and raw.get("release_decision_id") == record.release_decision_id
            and raw.get("release_decision_sha256") == record.release_decision_sha256
            and raw.get("reason_category") == record.reason_category
            and raw.get("reason") == record.reason
            and raw.get("stopped_by_user_id") == record.stopped_by_user_id
            and _same_timestamp(raw.get("created_at"), record.created_at)
            and raw.get("restart_requires_new_pilot_release") is True
        )
        if not valid:
            raise PilotExecutionIntegrityError("Pilot stop evidence failed its integrity check.")
        return PilotStopRead(
            id=record.id, release_decision_id=record.release_decision_id,
            release_decision_sha256=record.release_decision_sha256,
            reason_category=record.reason_category, reason=record.reason,
            stopped_by_user_id=record.stopped_by_user_id,
            sha256=record.sha256, created_at=record.created_at,
        )

    @staticmethod
    def _stop_record(db: Session, decision_id: str) -> PilotStopEvent | None:
        record = db.scalar(select(PilotStopEvent).where(
            PilotStopEvent.release_decision_id == decision_id
        ))
        if record is not None:
            PilotExecutionService._stop(record)
        return record

    @staticmethod
    def _active(db: Session, release: PilotReleaseDecision, now: datetime) -> None:
        if release.action != "authorize":
            raise PilotExecutionConflictError("This pilot release is on hold.")
        if release.starts_at is None or release.expires_at is None:
            raise PilotExecutionIntegrityError("Authorized pilot scope is incomplete.")
        if not (_to_utc(release.starts_at) <= now < _to_utc(release.expires_at)):
            raise PilotExecutionConflictError("The pilot authorization is outside its active time window.")
        if PilotExecutionService._stop_record(db, release.id) is not None:
            raise PilotExecutionConflictError(
                "The controlled pilot is stopped; a new release is required for restart."
            )

    @staticmethod
    def enroll(
        db: Session,
        release_id: str,
        visit_id: str,
        payload: PilotEnrollmentCreate,
        *,
        actor: User | None,
    ) -> PilotEnrollmentRead:
        if actor is None or not actor.is_active or actor.role != "physician":
            raise PilotExecutionAuthorizationError("Only an active physician may enroll a pilot visit.")
        if VisitRepository.get_by_id(db, visit_id) is None:
            raise PilotExecutionNotFoundError("The visit does not exist.")
        if db.new or db.dirty or db.deleted:
            raise PilotExecutionConflictError("Enrollment requires a clean transaction.")
        try:
            # Serialize visits first, then the release row. PostgreSQL serializes
            # concurrent enrollments under the release lock; SQLite serializes writers.
            db.execute(
                update(Visit).where(Visit.id == visit_id)
                .values(id=Visit.id, updated_at=Visit.updated_at)
                .execution_options(synchronize_session=False)
            )
            db.expire_all()
            release = PilotExecutionService._release(db, release_id, lock=True)
            if payload.expected_release_decision_sha256 != release.sha256:
                raise PilotExecutionConflictError("The pilot release hash changed.")
            now = datetime.now(timezone.utc)
            PilotExecutionService._active(db, release, now)
            if db.get_bind().dialect.name not in {"postgresql", "sqlite"}:
                raise PilotExecutionConflictError("Pilot enrollment requires a supported transactional database.")
            if db.scalar(select(PilotVisitEnrollment.id).where(
                PilotVisitEnrollment.visit_id == visit_id
            )) is not None:
                raise PilotExecutionConflictError("This visit was already enrolled in a pilot.")
            enrolled_count = db.scalar(
                select(func.count()).select_from(PilotVisitEnrollment)
                .where(PilotVisitEnrollment.release_decision_id == release.id)
            ) or 0
            if release.max_enrolled_visits is None or enrolled_count >= release.max_enrolled_visits:
                raise PilotExecutionConflictError("The pilot enrollment cap has been reached.")
            if TreatmentRepository.list_by_visit(db, visit_id, limit=1):
                raise PilotExecutionConflictError(
                    "The visit already has a treatment plan; prospective enrollment is required."
                )
            if payload.consent_confirmed_at > now + timedelta(minutes=5):
                raise PilotExecutionConflictError("Consent confirmation cannot be in the future.")
            protocol = ProtocolRepository.get_by_id(db, payload.protocol_template_id)
            if (
                protocol is None or not protocol.is_active
                or protocol.code not in release.allowed_protocol_codes
            ):
                raise PilotExecutionConflictError("The exact protocol is not active or outside pilot scope.")
            try:
                clinician = TreatmentDecisionService.get(db, payload.clinician_decision_id)
            except TreatmentDecisionIntegrityError as error:
                raise PilotExecutionIntegrityError(str(error)) from error
            if (
                clinician.visit_id != visit_id
                or not clinician.is_current_decision
                or clinician.sha256 != payload.expected_clinician_decision_sha256
                or clinician.decided_by_user_id != actor.id
                or clinician.decision_type in {"defer", "no_treatment"}
                or (protocol.code, protocol.version, protocol.treatment_type)
                not in {
                    (p.protocol_code, p.protocol_version, p.treatment_type)
                    for p in clinician.selected_protocols
                }
            ):
                raise PilotExecutionConflictError(
                    "Enrollment requires this physician's current, exact protocol-linked clinical decision."
                )
            frozen_protocol_sha = evidence_digest(
                ProtocolRead.model_validate(protocol).model_dump(mode="json")
            )
            # The launch package must still match the approved manual gates.
            package = PilotLaunchPackageService.get(db, release.package_id)
            try:
                PilotReleaseDecisionService._verify_package_still_current(db, package, settings)
            except Exception as error:
                raise PilotExecutionConflictError(
                    "The launch package prerequisites changed; suspend new enrollment."
                ) from error
            now = datetime.now(timezone.utc)
            PilotExecutionService._active(db, release, now)
            enrollment_id = str(uuid.uuid4())
            frozen = {
                "schema_version": 1, "id": enrollment_id,
                "release_decision_id": release.id, "release_decision_sha256": release.sha256,
                "visit_id": visit_id, "protocol_template_id": protocol.id,
                "protocol_snapshot_sha256": frozen_protocol_sha,
                "clinician_decision_id": clinician.id,
                "clinician_decision_sha256": clinician.sha256,
                "consent_evidence_reference": payload.consent_evidence_reference,
                "consent_confirmed_at": _to_utc(payload.consent_confirmed_at).isoformat(),
                "clinician_statement": payload.clinician_statement,
                "enrolled_by_user_id": actor.id, "created_at": now.isoformat(),
                "authorizes_individual_treatment": False,
                "confirms_patient_consent_document_authenticity": False,
            }
            record = PilotVisitEnrollment(
                id=enrollment_id, release_decision_id=release.id,
                release_decision_sha256=release.sha256, visit_id=visit_id,
                protocol_template_id=protocol.id, protocol_snapshot_sha256=frozen_protocol_sha,
                clinician_decision_id=clinician.id, clinician_decision_sha256=clinician.sha256,
                consent_evidence_reference=payload.consent_evidence_reference,
                consent_confirmed_at=_to_utc(payload.consent_confirmed_at),
                clinician_statement=payload.clinician_statement, enrolled_by_user_id=actor.id,
                payload=frozen, sha256=evidence_digest(frozen), created_at=now,
            )
            db.add(record)
            db.flush()
            AuditLogRepository.create(
                db, commit=False, entity_type="pilot_visit_enrollment",
                entity_id=enrollment_id, event_type="pilot_visit_enrolled",
                to_state="enrolled",
                event_data={"release_decision_id": release.id, "visit_id": visit_id,
                            "enrollment_sha256": record.sha256},
                **actor_data(actor),
            )
            db.commit()
            return PilotExecutionService._enrollment(record)
        except (IntegrityError, OperationalError) as error:
            db.rollback()
            raise PilotExecutionConflictError(
                "Pilot enrollment conflicted with a concurrent write; reload and retry."
            ) from error
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def stop(
        db: Session, release_id: str, payload: PilotStopCreate, *, actor: User | None,
    ) -> PilotStopRead:
        if actor is None or not actor.is_active or actor.role not in {"admin", "physician"}:
            raise PilotExecutionAuthorizationError(
                "Only an active administrator or physician may stop the pilot."
            )
        try:
            # The no-op update serializes a stop with concurrent enrollment
            # and pilot-activity checks without changing immutable release fields.
            db.execute(
                update(PilotReleaseDecision).where(PilotReleaseDecision.id == release_id)
                .values(id=PilotReleaseDecision.id)
                .execution_options(synchronize_session=False)
            )
            db.expire_all()
            release = PilotExecutionService._release(db, release_id, lock=True)
            if release.sha256 != payload.expected_release_decision_sha256:
                raise PilotExecutionConflictError("The pilot release hash changed.")
            if PilotExecutionService._stop_record(db, release.id) is not None:
                raise PilotExecutionConflictError("This pilot has already been stopped.")
            now = datetime.now(timezone.utc)
            stop_id = str(uuid.uuid4())
            frozen = {
                "schema_version": 1, "id": stop_id,
                "release_decision_id": release.id,
                "release_decision_sha256": release.sha256,
                "reason_category": payload.reason_category,
                "reason": payload.reason,
                "stopped_by_user_id": actor.id,
                "created_at": now.isoformat(),
                "restart_requires_new_pilot_release": True,
            }
            record = PilotStopEvent(
                id=stop_id, release_decision_id=release.id,
                release_decision_sha256=release.sha256,
                reason_category=payload.reason_category,
                reason=payload.reason, stopped_by_user_id=actor.id,
                payload=frozen, sha256=evidence_digest(frozen), created_at=now,
            )
            db.add(record)
            db.flush()
            AuditLogRepository.create(
                db, commit=False, entity_type="pilot_stop_event",
                entity_id=record.id, event_type="controlled_pilot_stopped",
                to_state="stopped",
                event_data={"release_decision_id": release.id, "stop_sha256": record.sha256},
                **actor_data(actor),
            )
            db.commit()
            return PilotExecutionService._stop(record)
        except (IntegrityError, OperationalError) as error:
            db.rollback()
            raise PilotExecutionConflictError("The pilot stop conflicted with another write.") from error
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def get_enrollment(db: Session, visit_id: str) -> PilotEnrollmentRead | None:
        record = db.scalar(
            select(PilotVisitEnrollment).where(PilotVisitEnrollment.visit_id == visit_id)
        )
        return PilotExecutionService._enrollment(record) if record is not None else None

    @staticmethod
    def list_enrollments(db: Session, decision_id: str) -> list[PilotEnrollmentRead]:
        PilotExecutionService._release(db, decision_id)
        rows = db.scalars(
            select(PilotVisitEnrollment)
            .where(PilotVisitEnrollment.release_decision_id == decision_id)
            .order_by(PilotVisitEnrollment.created_at, PilotVisitEnrollment.id)
        ).all()
        return [PilotExecutionService._enrollment(record) for record in rows]

    @staticmethod
    def get_stop(db: Session, decision_id: str) -> PilotStopRead | None:
        PilotExecutionService._release(db, decision_id)
        record = PilotExecutionService._stop_record(db, decision_id)
        return PilotExecutionService._stop(record) if record is not None else None

    @staticmethod
    def require_visit_eligible(
        db: Session, visit_id: str, *, protocol_template_id: str | None,
        clinician_decision_id: str | None, now: datetime | None = None,
    ) -> None:
        record = db.scalar(
            select(PilotVisitEnrollment).where(PilotVisitEnrollment.visit_id == visit_id)
        )
        if record is None:
            if settings.PILOT_ENFORCEMENT_ENABLED:
                raise PilotExecutionConflictError(
                    "Pilot enforcement is enabled: an enrolled visit is required."
                )
            return
        PilotExecutionService._enrollment(record)
        release = PilotExecutionService._release(db, record.release_decision_id, lock=True)
        if release.sha256 != record.release_decision_sha256:
            raise PilotExecutionIntegrityError("Enrollment and pilot release hashes differ.")
        PilotExecutionService._active(db, release, now or datetime.now(timezone.utc))
        if protocol_template_id != record.protocol_template_id:
            raise PilotExecutionConflictError("The protocol differs from the enrolled pilot scope.")
        if clinician_decision_id != record.clinician_decision_id:
            raise PilotExecutionConflictError(
                "The treatment is not linked to the enrollment's clinician decision."
            )
        protocol = ProtocolRepository.get_by_id(db, record.protocol_template_id)
        if protocol is None or not protocol.is_active or protocol.code not in release.allowed_protocol_codes:
            raise PilotExecutionConflictError("The enrolled protocol is no longer active or in scope.")
        if evidence_digest(ProtocolRead.model_validate(protocol).model_dump(mode="json")) != record.protocol_snapshot_sha256:
            raise PilotExecutionConflictError("The enrolled protocol snapshot changed.")
        clinician = TreatmentDecisionService.get_current_record(db, visit_id)
        if clinician is None or clinician.id != record.clinician_decision_id or clinician.sha256 != record.clinician_decision_sha256:
            raise PilotExecutionConflictError(
                "The clinician decision was superseded; a new pilot enrollment is required."
            )

    @staticmethod
    def require_treatment_eligible(db: Session, treatment_id: str) -> None:
        treatment = db.get(Treatment, treatment_id)
        if treatment is None:
            raise PilotExecutionNotFoundError("Treatment was not found.")
        PilotExecutionService.require_visit_eligible(
            db, treatment.visit_id,
            protocol_template_id=treatment.protocol_template_id,
            clinician_decision_id=treatment.source_treatment_decision_id,
        )

    @staticmethod
    def operations(db: Session, decision_id: str) -> PilotOperationsRead:
        release = PilotExecutionService._release(db, decision_id)
        count = len(PilotExecutionService.list_enrollments(db, decision_id))
        stop = PilotExecutionService._stop_record(db, decision_id)
        now = datetime.now(timezone.utc)
        if stop is not None:
            state = "stopped"
        elif release.action != "authorize":
            state = "held"
        elif now < _to_utc(release.starts_at):
            state = "scheduled"
        elif now >= _to_utc(release.expires_at):
            state = "expired"
        else:
            state = "active"
        cap = release.max_enrolled_visits or 0
        remaining = max(0, cap - count)
        return PilotOperationsRead(
            release_decision_id=release.id, release_decision_sha256=release.sha256,
            status=state, enrolled_visits=count, max_enrolled_visits=release.max_enrolled_visits,
            remaining_enrollment_slots=remaining, stopped=stop is not None,
            stop_sha256=(stop.sha256 if stop else None),
            new_pilot_activity_allowed=state == "active",
        )

    @staticmethod
    def acceptance(db: Session, decision_id: str) -> PilotAcceptanceRead:
        from backend.app.services.treatment_outcome import (
            TreatmentOutcomeIntegrityError, TreatmentOutcomeService,
        )
        operations = PilotExecutionService.operations(db, decision_id)
        enrollments = PilotExecutionService.list_enrollments(db, decision_id)
        treatment_visits = 0
        outcome_visits = 0
        outcomes = []
        for enrollment in enrollments:
            treatments = TreatmentRepository.list_by_visit(db, enrollment.visit_id)
            if treatments:
                treatment_visits += 1
            records = db.scalars(
                select(TreatmentOutcome)
                .where(TreatmentOutcome.visit_id == enrollment.visit_id)
                .order_by(TreatmentOutcome.recorded_at, TreatmentOutcome.id)
            ).all()
            if records:
                outcome_visits += 1
            for record in records:
                try:
                    TreatmentOutcomeService._validate(db, record)
                except TreatmentOutcomeIntegrityError as error:
                    raise PilotExecutionIntegrityError(
                        "A pilot outcome failed its integrity check."
                    ) from error
                outcomes.append(record)
        hashes = sorted(record.sha256 for record in outcomes)
        evidence = {
            "schema_version": 1,
            "release_decision_id": decision_id,
            "release_decision_sha256": operations.release_decision_sha256,
            "enrollment_sha256s": sorted(item.sha256 for item in enrollments),
            "outcome_sha256s": hashes,
            "stop_sha256": operations.stop_sha256,
        }
        status = (
            "no_pilot_data" if not enrollments else
            "follow_up_incomplete" if (
                treatment_visits < len(enrollments)
                or outcome_visits < len(enrollments)
            ) else "ready_for_human_review"
        )
        return PilotAcceptanceRead(
            release_decision_id=decision_id,
            release_decision_sha256=operations.release_decision_sha256,
            generated_at=datetime.now(timezone.utc),
            operations_status=operations.status,
            enrolled_visits=len(enrollments),
            visits_with_treatment=treatment_visits,
            visits_with_outcome=outcome_visits,
            total_outcome_observations=len(outcomes),
            total_reported_adverse_event_entries=sum(len(r.adverse_events) for r in outcomes),
            enrollment_sha256s=evidence["enrollment_sha256s"],
            outcome_sha256s=hashes,
            stop_sha256=operations.stop_sha256,
            evidence_manifest_sha256=evidence_digest(evidence),
            status=status,
        )
