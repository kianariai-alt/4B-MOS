"""Two-step human release decision bound to an immutable launch package."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.models.user import User
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.repositories.pilot_release import PilotReleaseDecisionRepository
from backend.app.schemas.pilot_release import (
    PilotReleaseDecisionCreate,
    PilotReleaseDecisionRead,
    PilotReleaseEndorsementCreate,
    PilotReleaseEndorsementRead,
    PilotReleaseStatusRead,
)
from backend.app.services.audit_context import actor_data
from backend.app.services.pilot_launch import (
    PilotLaunchPackageIntegrityError,
    PilotLaunchPackageNotFoundError,
    PilotLaunchPackageService,
)
from backend.app.services.pilot_readiness import ControlledPilotReadinessService
from backend.app.services.pilot_release import (
    ALL_GATES,
    PilotManualGateIntegrityError,
    PilotManualGateService,
)
from backend.app.services.session_finalization import evidence_digest


class PilotReleaseDecisionNotFoundError(Exception):
    pass


class PilotReleaseDecisionConflictError(Exception):
    pass


class PilotReleaseDecisionAuthorizationError(Exception):
    pass


class PilotReleaseDecisionIntegrityError(Exception):
    pass


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _same_timestamp(payload_value: str, column_value: datetime) -> bool:
    try:
        parsed = datetime.fromisoformat(payload_value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return False
    return _as_utc(parsed) == _as_utc(column_value)


class PilotReleaseDecisionService:
    @staticmethod
    def _require_role(actor: User | None, role: str) -> User:
        if actor is None or not actor.is_active or actor.role != role:
            raise PilotReleaseDecisionAuthorizationError(
                f"This release action requires an active {role}."
            )
        return actor

    @staticmethod
    def _validate_endorsement(record, package_sha256: str):
        raw = deepcopy(record.payload)
        try:
            valid = (
                isinstance(raw, dict)
                and evidence_digest(raw) == record.sha256
                and raw.get("schema_version") == 1
                and raw.get("id") == record.id
                and raw.get("package_id") == record.package_id
                and raw.get("package_sha256") == record.package_sha256
                and record.package_sha256 == package_sha256
                and raw.get("action") == record.action
                and raw.get("rationale") == record.rationale
                and raw.get("endorsed_by_user_id")
                == record.endorsed_by_user_id
                and _same_timestamp(raw.get("created_at"), record.created_at)
                and raw.get("append_only") is True
                and raw.get("is_clinical_clearance") is False
                and raw.get("authorizes_specific_patient_treatment") is False
            )
        except (AttributeError, TypeError, ValueError):
            valid = False
        if not valid:
            raise PilotReleaseDecisionIntegrityError(
                "Stored pilot release endorsement failed its integrity check."
            )

    @staticmethod
    def _validate_decision(
        record,
        *,
        package_sha256: str,
        endorsement_sha256: str,
    ):
        raw = deepcopy(record.payload)
        try:
            authorized = record.action == "authorize_controlled_pilot"
            valid = (
                isinstance(raw, dict)
                and evidence_digest(raw) == record.sha256
                and raw.get("schema_version") == 1
                and raw.get("id") == record.id
                and raw.get("package_id") == record.package_id
                and raw.get("package_sha256") == record.package_sha256
                and record.package_sha256 == package_sha256
                and raw.get("endorsement_id") == record.endorsement_id
                and raw.get("endorsement_sha256")
                == record.endorsement_sha256
                and record.endorsement_sha256 == endorsement_sha256
                and raw.get("action") == record.action
                and raw.get("rationale") == record.rationale
                and raw.get("decided_by_user_id")
                == record.decided_by_user_id
                and _same_timestamp(raw.get("created_at"), record.created_at)
                and raw.get("acknowledgement") is True
                and raw.get("append_only") is True
                and raw.get("controlled_pilot_authorized") is authorized
                and raw.get("is_clinical_clearance") is False
                and raw.get("authorizes_specific_patient_treatment") is False
            )
        except (AttributeError, TypeError, ValueError):
            valid = False
        if not valid:
            raise PilotReleaseDecisionIntegrityError(
                "Stored pilot release decision failed its integrity check."
            )

    @staticmethod
    def _endorsement_read(record) -> PilotReleaseEndorsementRead:
        return PilotReleaseEndorsementRead(
            id=record.id,
            package_id=record.package_id,
            package_sha256=record.package_sha256,
            action=record.action,
            rationale=record.rationale,
            endorsed_by_user_id=record.endorsed_by_user_id,
            sha256=record.sha256,
            created_at=record.created_at,
        )

    @staticmethod
    def _decision_read(record) -> PilotReleaseDecisionRead:
        return PilotReleaseDecisionRead(
            id=record.id,
            package_id=record.package_id,
            package_sha256=record.package_sha256,
            endorsement_id=record.endorsement_id,
            endorsement_sha256=record.endorsement_sha256,
            action=record.action,
            rationale=record.rationale,
            decided_by_user_id=record.decided_by_user_id,
            sha256=record.sha256,
            created_at=record.created_at,
            controlled_pilot_authorized=(
                record.action == "authorize_controlled_pilot"
            ),
        )

    @staticmethod
    def _current_evidence_matches(
        db: Session,
        package,
        config: Settings,
    ) -> bool:
        readiness = ControlledPilotReadinessService.build(db, config)
        if (
            readiness.status != "automated_prerequisites_passed"
            or readiness.readiness_sha256 != package.readiness_sha256
        ):
            return False

        try:
            statuses = PilotManualGateService.list_statuses(db)
        except PilotManualGateIntegrityError as error:
            raise PilotReleaseDecisionIntegrityError(str(error)) from error

        by_gate = {item.gate_name: item for item in statuses}
        current_manifest = []
        for gate_name in sorted(ALL_GATES):
            state = by_gate.get(gate_name)
            if (
                state is None
                or state.status != "approved"
                or state.latest_attestation is None
                or state.latest_attestation.review is None
                or state.latest_attestation.review.action != "approve"
            ):
                return False
            latest = state.latest_attestation
            if (
                latest.readiness_sha256 != package.readiness_sha256
                or latest.release_ref != package.release_ref
            ):
                return False
            current_manifest.append(
                {
                    "gate_name": gate_name,
                    "generation": latest.generation,
                    "attestation_id": latest.id,
                    "attestation_sha256": latest.sha256,
                    "review_id": latest.review.id,
                    "review_sha256": latest.review.sha256,
                }
            )

        frozen_manifest = [
            item.model_dump(mode="json")
            for item in package.attestation_manifest
        ]
        return current_manifest == frozen_manifest

    @staticmethod
    def get_status(
        db: Session,
        package_id: str,
        config: Settings,
    ) -> PilotReleaseStatusRead:
        try:
            package = PilotLaunchPackageService.get(db, package_id)
        except PilotLaunchPackageNotFoundError as error:
            raise PilotReleaseDecisionNotFoundError(str(error)) from error
        except PilotLaunchPackageIntegrityError as error:
            raise PilotReleaseDecisionIntegrityError(str(error)) from error

        evidence_matches = PilotReleaseDecisionService._current_evidence_matches(
            db,
            package,
            config,
        )
        endorsement = PilotReleaseDecisionRepository.get_endorsement_by_package(
            db,
            package_id,
        )
        endorsement_read = None
        if endorsement is not None:
            PilotReleaseDecisionService._validate_endorsement(
                endorsement,
                package.sha256,
            )
            endorsement_read = PilotReleaseDecisionService._endorsement_read(
                endorsement
            )

        decision = PilotReleaseDecisionRepository.get_decision_by_package(
            db,
            package_id,
        )
        decision_read = None
        if decision is not None:
            if endorsement is None:
                raise PilotReleaseDecisionIntegrityError(
                    "Release decision exists without its physician endorsement."
                )
            PilotReleaseDecisionService._validate_decision(
                decision,
                package_sha256=package.sha256,
                endorsement_sha256=endorsement.sha256,
            )
            decision_read = PilotReleaseDecisionService._decision_read(decision)

        if not evidence_matches:
            status = "stale_evidence"
        elif decision_read is not None:
            status = (
                "authorized_controlled_pilot"
                if decision_read.action == "authorize_controlled_pilot"
                else "admin_hold"
            )
        elif endorsement_read is None:
            status = "awaiting_physician_endorsement"
        elif endorsement_read.action == "hold":
            status = "physician_hold"
        else:
            status = "awaiting_admin_decision"

        return PilotReleaseStatusRead(
            package=package,
            evidence_matches_current_state=evidence_matches,
            endorsement=endorsement_read,
            decision=decision_read,
            status=status,
        )

    @staticmethod
    def create_endorsement(
        db: Session,
        package_id: str,
        payload: PilotReleaseEndorsementCreate,
        *,
        actor: User | None,
        config: Settings,
    ) -> PilotReleaseStatusRead:
        actor = PilotReleaseDecisionService._require_role(actor, "physician")
        status = PilotReleaseDecisionService.get_status(
            db,
            package_id,
            config,
        )
        if not status.evidence_matches_current_state:
            raise PilotReleaseDecisionConflictError(
                "Launch package evidence no longer matches current release state."
            )
        if status.endorsement is not None:
            raise PilotReleaseDecisionConflictError(
                "This launch package already has an immutable physician endorsement."
            )
        if payload.expected_package_sha256 != status.package.sha256:
            raise PilotReleaseDecisionConflictError(
                "Launch package changed; reload before endorsement."
            )

        now = datetime.now(timezone.utc)
        endorsement_id = str(uuid.uuid4())
        frozen = {
            "schema_version": 1,
            "id": endorsement_id,
            "package_id": status.package.id,
            "package_sha256": status.package.sha256,
            "action": payload.action,
            "rationale": payload.rationale.strip(),
            "endorsed_by_user_id": actor.id,
            "created_at": now.isoformat(),
            "append_only": True,
            "is_clinical_clearance": False,
            "authorizes_specific_patient_treatment": False,
        }
        sha256 = evidence_digest(frozen)
        try:
            record = PilotReleaseDecisionRepository.create_endorsement(
                db,
                endorsement_id=endorsement_id,
                package_id=status.package.id,
                package_sha256=status.package.sha256,
                action=payload.action,
                rationale=payload.rationale.strip(),
                endorsed_by_user_id=actor.id,
                payload=frozen,
                sha256=sha256,
                created_at=now,
            )
            AuditLogRepository.create(
                db,
                entity_type="pilot_launch_package",
                entity_id=status.package.id,
                event_type="pilot_release_physician_endorsed",
                from_state="awaiting_physician_endorsement",
                to_state=(
                    "awaiting_admin_decision"
                    if record.action == "endorse"
                    else "physician_hold"
                ),
                event_data={
                    "package_sha256": status.package.sha256,
                    "endorsement_sha256": record.sha256,
                    "action": record.action,
                },
                commit=False,
                **actor_data(actor),
            )
            db.commit()
        except IntegrityError as error:
            db.rollback()
            raise PilotReleaseDecisionConflictError(
                "Another physician endorsement was recorded first."
            ) from error
        except Exception:
            db.rollback()
            raise
        return PilotReleaseDecisionService.get_status(db, package_id, config)

    @staticmethod
    def create_decision(
        db: Session,
        package_id: str,
        payload: PilotReleaseDecisionCreate,
        *,
        actor: User | None,
        config: Settings,
    ) -> PilotReleaseStatusRead:
        actor = PilotReleaseDecisionService._require_role(actor, "admin")
        status = PilotReleaseDecisionService.get_status(
            db,
            package_id,
            config,
        )
        if not status.evidence_matches_current_state:
            raise PilotReleaseDecisionConflictError(
                "Launch package evidence no longer matches current release state."
            )
        if status.decision is not None:
            raise PilotReleaseDecisionConflictError(
                "This launch package already has an immutable release decision."
            )
        if status.endorsement is None:
            raise PilotReleaseDecisionConflictError(
                "Physician endorsement is required before the release decision."
            )
        if payload.expected_package_sha256 != status.package.sha256:
            raise PilotReleaseDecisionConflictError(
                "Launch package changed; reload before release decision."
            )
        if payload.expected_endorsement_sha256 != status.endorsement.sha256:
            raise PilotReleaseDecisionConflictError(
                "Physician endorsement changed; reload before release decision."
            )
        if (
            payload.action == "authorize_controlled_pilot"
            and status.endorsement.action != "endorse"
        ):
            raise PilotReleaseDecisionConflictError(
                "Controlled pilot authorization requires physician endorsement."
            )

        now = datetime.now(timezone.utc)
        decision_id = str(uuid.uuid4())
        authorized = payload.action == "authorize_controlled_pilot"
        frozen = {
            "schema_version": 1,
            "id": decision_id,
            "package_id": status.package.id,
            "package_sha256": status.package.sha256,
            "endorsement_id": status.endorsement.id,
            "endorsement_sha256": status.endorsement.sha256,
            "action": payload.action,
            "rationale": payload.rationale.strip(),
            "decided_by_user_id": actor.id,
            "created_at": now.isoformat(),
            "acknowledgement": True,
            "append_only": True,
            "controlled_pilot_authorized": authorized,
            "is_clinical_clearance": False,
            "authorizes_specific_patient_treatment": False,
        }
        sha256 = evidence_digest(frozen)
        try:
            record = PilotReleaseDecisionRepository.create_decision(
                db,
                decision_id=decision_id,
                package_id=status.package.id,
                package_sha256=status.package.sha256,
                endorsement_id=status.endorsement.id,
                endorsement_sha256=status.endorsement.sha256,
                action=payload.action,
                rationale=payload.rationale.strip(),
                decided_by_user_id=actor.id,
                payload=frozen,
                sha256=sha256,
                created_at=now,
            )
            AuditLogRepository.create(
                db,
                entity_type="pilot_launch_package",
                entity_id=status.package.id,
                event_type="pilot_release_decision_recorded",
                from_state="awaiting_admin_decision",
                to_state=(
                    "authorized_controlled_pilot"
                    if authorized
                    else "admin_hold"
                ),
                event_data={
                    "package_sha256": status.package.sha256,
                    "endorsement_sha256": status.endorsement.sha256,
                    "decision_sha256": record.sha256,
                    "action": record.action,
                    "controlled_pilot_authorized": authorized,
                    "is_clinical_clearance": False,
                },
                commit=False,
                **actor_data(actor),
            )
            db.commit()
        except IntegrityError as error:
            db.rollback()
            raise PilotReleaseDecisionConflictError(
                "Another release decision was recorded first."
            ) from error
        except Exception:
            db.rollback()
            raise
        return PilotReleaseDecisionService.get_status(db, package_id, config)
