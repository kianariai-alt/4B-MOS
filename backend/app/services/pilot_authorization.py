"""Human release decision bound to one immutable pilot launch package."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.models.user import User
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.repositories.pilot_release import (
    PilotReleaseDecisionRepository,
)
from backend.app.repositories.protocol import ProtocolRepository
from backend.app.schemas.pilot_release import (
    PilotReleaseDecisionCreate,
    PilotReleaseDecisionRead,
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
    def _require_admin(actor: User | None) -> User:
        if actor is None or not actor.is_active or actor.role != "admin":
            raise PilotReleaseDecisionAuthorizationError(
                "Only an active administrator may record a pilot release decision."
            )
        return actor

    @staticmethod
    def _validate(record):
        raw = deepcopy(record.payload)
        try:
            valid = (
                isinstance(raw, dict)
                and evidence_digest(raw) == record.sha256
                and raw.get("schema_version") == 1
                and raw.get("id") == record.id
                and raw.get("package_id") == record.package_id
                and raw.get("package_sha256") == record.package_sha256
                and raw.get("action") == record.action
                and raw.get("starts_at")
                == (
                    _as_utc(record.starts_at).isoformat()
                    if record.starts_at is not None
                    else None
                )
                and raw.get("expires_at")
                == (
                    _as_utc(record.expires_at).isoformat()
                    if record.expires_at is not None
                    else None
                )
                and raw.get("max_enrolled_visits") == record.max_enrolled_visits
                and raw.get("allowed_protocol_codes")
                == list(record.allowed_protocol_codes)
                and raw.get("rationale") == record.rationale
                and raw.get("decided_by_user_id") == record.decided_by_user_id
                and _same_timestamp(raw.get("created_at"), record.created_at)
                and raw.get("append_only") is True
                and raw.get("authorizes_individual_treatment") is False
                and raw.get("is_clinical_clearance") is False
                and raw.get("individual_clinician_decision_required") is True
            )
        except (AttributeError, TypeError, ValueError):
            valid = False
        if not valid:
            raise PilotReleaseDecisionIntegrityError(
                "Stored pilot release decision failed its integrity check."
            )
        return raw

    @staticmethod
    def _to_read(record) -> PilotReleaseDecisionRead:
        PilotReleaseDecisionService._validate(record)
        return PilotReleaseDecisionRead(
            id=record.id,
            package_id=record.package_id,
            package_sha256=record.package_sha256,
            action=record.action,
            starts_at=record.starts_at,
            expires_at=record.expires_at,
            max_enrolled_visits=record.max_enrolled_visits,
            allowed_protocol_codes=list(record.allowed_protocol_codes),
            rationale=record.rationale,
            decided_by_user_id=record.decided_by_user_id,
            sha256=record.sha256,
            created_at=record.created_at,
            controlled_pilot_release_authorized=record.action == "authorize",
        )

    @staticmethod
    def _verify_package_still_current(
        db: Session,
        package,
        config: Settings,
    ) -> None:
        readiness = ControlledPilotReadinessService.build(db, config)
        if readiness.status != "automated_prerequisites_passed":
            raise PilotReleaseDecisionConflictError(
                "Automated pilot prerequisites are no longer passing."
            )
        if readiness.readiness_sha256 != package.readiness_sha256:
            raise PilotReleaseDecisionConflictError(
                "Pilot readiness changed after the launch package was frozen."
            )

        try:
            statuses = PilotManualGateService.list_statuses(db)
        except PilotManualGateIntegrityError as error:
            raise PilotReleaseDecisionIntegrityError(str(error)) from error

        by_gate = {item.gate_name: item for item in statuses}
        manifest = {
            item.gate_name: item.attestation_sha256
            for item in package.attestation_manifest
        }
        if set(manifest) != set(ALL_GATES):
            raise PilotReleaseDecisionIntegrityError(
                "Launch package manual-gate manifest is incomplete."
            )
        for gate_name in ALL_GATES:
            state = by_gate.get(gate_name)
            if (
                state is None
                or state.status != "approved"
                or state.latest_attestation is None
                or state.latest_attestation.sha256 != manifest[gate_name]
            ):
                raise PilotReleaseDecisionConflictError(
                    "Manual gate evidence changed after the launch package "
                    "was frozen."
                )

    @staticmethod
    def create(
        db: Session,
        package_id: str,
        payload: PilotReleaseDecisionCreate,
        *,
        actor: User | None,
        config: Settings,
    ) -> PilotReleaseDecisionRead:
        actor = PilotReleaseDecisionService._require_admin(actor)
        try:
            package = PilotLaunchPackageService.get(db, package_id)
        except PilotLaunchPackageNotFoundError as error:
            raise PilotReleaseDecisionNotFoundError(str(error)) from error
        except PilotLaunchPackageIntegrityError as error:
            raise PilotReleaseDecisionIntegrityError(str(error)) from error

        if package.sha256 != payload.expected_package_sha256:
            raise PilotReleaseDecisionConflictError(
                "Launch package changed; reload it before deciding."
            )
        if actor.id == package.created_by_user_id:
            raise PilotReleaseDecisionAuthorizationError(
                "The launch package author cannot make the human release decision."
            )
        if PilotReleaseDecisionRepository.get_by_package(db, package.id) is not None:
            raise PilotReleaseDecisionConflictError(
                "A human release decision already exists for this launch package."
            )

        PilotReleaseDecisionService._verify_package_still_current(
            db,
            package,
            config,
        )

        starts_at = payload.starts_at
        expires_at = payload.expires_at
        allowed_protocol_codes = list(payload.allowed_protocol_codes)
        max_visits = payload.max_enrolled_visits

        if payload.action == "authorize":
            now = datetime.now(timezone.utc)
            if expires_at is None or _as_utc(expires_at) <= now:
                raise PilotReleaseDecisionConflictError(
                    "Pilot authorization expiry must be in the future."
                )
            protocols = ProtocolRepository.list(db)
            active_codes = {item.code for item in protocols if item.is_active}
            if not set(allowed_protocol_codes) <= active_codes:
                raise PilotReleaseDecisionConflictError(
                    "Pilot scope references a protocol that is not currently active."
                )

        now = datetime.now(timezone.utc)
        decision_id = str(uuid.uuid4())
        frozen = {
            "schema_version": 1,
            "id": decision_id,
            "package_id": package.id,
            "package_sha256": package.sha256,
            "action": payload.action,
            "starts_at": (
                _as_utc(starts_at).isoformat()
                if starts_at is not None
                else None
            ),
            "expires_at": (
                _as_utc(expires_at).isoformat()
                if expires_at is not None
                else None
            ),
            "max_enrolled_visits": max_visits,
            "allowed_protocol_codes": allowed_protocol_codes,
            "rationale": payload.rationale.strip(),
            "decided_by_user_id": actor.id,
            "created_at": now.isoformat(),
            "append_only": True,
            "authorizes_individual_treatment": False,
            "is_clinical_clearance": False,
            "individual_clinician_decision_required": True,
        }
        sha256 = evidence_digest(frozen)
        try:
            record = PilotReleaseDecisionRepository.create(
                db,
                decision_id=decision_id,
                package_id=package.id,
                package_sha256=package.sha256,
                action=payload.action,
                starts_at=starts_at,
                expires_at=expires_at,
                max_enrolled_visits=max_visits,
                allowed_protocol_codes=allowed_protocol_codes,
                rationale=payload.rationale.strip(),
                decided_by_user_id=actor.id,
                payload=frozen,
                sha256=sha256,
                created_at=now,
            )
            AuditLogRepository.create(
                db,
                entity_type="pilot_release_decision",
                entity_id=record.id,
                event_type="pilot_release_decision_recorded",
                to_state=payload.action,
                event_data={
                    "package_id": package.id,
                    "package_sha256": package.sha256,
                    "decision_sha256": sha256,
                    "action": payload.action,
                    "max_enrolled_visits": max_visits,
                    "allowed_protocol_count": len(allowed_protocol_codes),
                },
                commit=False,
                **actor_data(actor),
            )
            db.commit()
        except IntegrityError as error:
            db.rollback()
            raise PilotReleaseDecisionConflictError(
                "A release decision already exists for this launch package."
            ) from error
        except Exception:
            db.rollback()
            raise
        return PilotReleaseDecisionService._to_read(record)

    @staticmethod
    def get(
        db: Session,
        decision_id: str,
    ) -> PilotReleaseDecisionRead:
        record = PilotReleaseDecisionRepository.get(db, decision_id)
        if record is None:
            raise PilotReleaseDecisionNotFoundError(
                f"Pilot release decision '{decision_id}' was not found."
            )
        return PilotReleaseDecisionService._to_read(record)

    @staticmethod
    def get_by_package(
        db: Session,
        package_id: str,
    ) -> PilotReleaseDecisionRead | None:
        record = PilotReleaseDecisionRepository.get_by_package(db, package_id)
        return (
            PilotReleaseDecisionService._to_read(record)
            if record is not None
            else None
        )

    @staticmethod
    def list(db: Session) -> list[PilotReleaseDecisionRead]:
        return [
            PilotReleaseDecisionService._to_read(item)
            for item in PilotReleaseDecisionRepository.list(db)
        ]
