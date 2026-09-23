"""Governed manual acceptance gates for controlled-pilot release evidence."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import uuid

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.models.user import User
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.repositories.pilot_release import PilotManualGateRepository
from backend.app.schemas.pilot_release import (
    PilotManualGateAttestationCreate,
    PilotManualGateAttestationRead,
    PilotManualGateReviewCreate,
    PilotManualGateReviewRead,
    PilotManualGateStatusRead,
)
from backend.app.services.audit_context import actor_data
from backend.app.services.pilot_readiness import ControlledPilotReadinessService
from backend.app.services.session_finalization import evidence_digest


CLINICAL_GATES = {
    "clinical_protocol_signoff",
    "clinical_safety_signoff",
}
OPERATIONAL_GATES = {
    "backup_restore",
    "security_perimeter",
    "monitoring_alerting",
    "human_ui_acceptance",
    "privacy_retention_legal",
}
ALL_GATES = CLINICAL_GATES | OPERATIONAL_GATES


class PilotManualGateNotFoundError(Exception):
    pass


class PilotManualGateConflictError(Exception):
    pass


class PilotManualGateAuthorizationError(Exception):
    pass


class PilotManualGateIntegrityError(Exception):
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


class PilotManualGateService:
    @staticmethod
    def _required_role(gate_name: str) -> str:
        if gate_name in CLINICAL_GATES:
            return "physician"
        if gate_name in OPERATIONAL_GATES:
            return "admin"
        raise PilotManualGateConflictError("Unknown manual gate.")

    @staticmethod
    def _require_actor(actor: User | None, gate_name: str) -> User:
        expected = PilotManualGateService._required_role(gate_name)
        if actor is None or not actor.is_active or actor.role != expected:
            raise PilotManualGateAuthorizationError(
                f"Gate '{gate_name}' requires an active {expected}."
            )
        return actor

    @staticmethod
    def _validate_attestation(record):
        raw = deepcopy(record.payload)
        try:
            valid = (
                isinstance(raw, dict)
                and evidence_digest(raw) == record.sha256
                and raw.get("schema_version") == 1
                and raw.get("id") == record.id
                and raw.get("gate_name") == record.gate_name
                and raw.get("readiness_sha256") == record.readiness_sha256
                and raw.get("generation") == record.generation
                and raw.get("release_ref") == record.release_ref
                and raw.get("evidence_reference") == record.evidence_reference
                and raw.get("statement") == record.statement
                and raw.get("supersedes_attestation_id")
                == record.supersedes_attestation_id
                and raw.get("attested_by_user_id")
                == record.attested_by_user_id
                and raw.get("attested_by_role") == record.attested_by_role
                and _same_timestamp(raw.get("created_at"), record.created_at)
                and raw.get("append_only") is True
                and raw.get("independent_review_required") is True
                and raw.get("is_clinical_clearance") is False
                and raw.get("controlled_pilot_authorized") is False
            )
        except (AttributeError, TypeError, ValueError):
            valid = False
        if not valid:
            raise PilotManualGateIntegrityError(
                "Stored manual gate attestation failed its integrity check."
            )
        return raw

    @staticmethod
    def _validate_review(record, attestation_sha256: str):
        raw = deepcopy(record.payload)
        try:
            valid = (
                isinstance(raw, dict)
                and evidence_digest(raw) == record.sha256
                and raw.get("schema_version") == 1
                and raw.get("id") == record.id
                and raw.get("attestation_id") == record.attestation_id
                and raw.get("attestation_sha256") == record.attestation_sha256
                and record.attestation_sha256 == attestation_sha256
                and raw.get("action") == record.action
                and raw.get("rationale") == record.rationale
                and raw.get("reviewed_by_user_id")
                == record.reviewed_by_user_id
                and raw.get("reviewed_by_role") == record.reviewed_by_role
                and _same_timestamp(raw.get("created_at"), record.created_at)
                and raw.get("independent_review") is True
                and raw.get("is_clinical_clearance") is False
                and raw.get("controlled_pilot_authorized") is False
            )
        except (AttributeError, TypeError, ValueError):
            valid = False
        if not valid:
            raise PilotManualGateIntegrityError(
                "Stored manual gate review failed its integrity check."
            )
        return raw

    @staticmethod
    def _to_read(db: Session, record) -> PilotManualGateAttestationRead:
        PilotManualGateService._validate_attestation(record)
        review = PilotManualGateRepository.get_review_by_attestation(
            db,
            record.id,
        )
        review_read = None
        status = "pending_review"
        if review is not None:
            PilotManualGateService._validate_review(review, record.sha256)
            review_read = PilotManualGateReviewRead(
                id=review.id,
                attestation_id=review.attestation_id,
                attestation_sha256=review.attestation_sha256,
                action=review.action,
                rationale=review.rationale,
                reviewed_by_user_id=review.reviewed_by_user_id,
                reviewed_by_role=review.reviewed_by_role,
                sha256=review.sha256,
                created_at=review.created_at,
            )
            status = "approved" if review.action == "approve" else "rejected"
        return PilotManualGateAttestationRead(
            id=record.id,
            gate_name=record.gate_name,
            readiness_sha256=record.readiness_sha256,
            generation=record.generation,
            release_ref=record.release_ref,
            evidence_reference=record.evidence_reference,
            statement=record.statement,
            supersedes_attestation_id=record.supersedes_attestation_id,
            attested_by_user_id=record.attested_by_user_id,
            attested_by_role=record.attested_by_role,
            sha256=record.sha256,
            created_at=record.created_at,
            status=status,
            review=review_read,
        )

    @staticmethod
    def _current_ready_snapshot(
        db: Session,
        config: Settings,
        expected_sha256: str,
    ):
        readiness = ControlledPilotReadinessService.build(db, config)
        if readiness.status != "automated_prerequisites_passed":
            raise PilotManualGateConflictError(
                "Automated pilot prerequisites are not currently passing."
            )
        if readiness.readiness_sha256 != expected_sha256:
            raise PilotManualGateConflictError(
                "Pilot readiness changed; reload before attesting."
            )
        return readiness

    @staticmethod
    def create_attestation(
        db: Session,
        payload: PilotManualGateAttestationCreate,
        *,
        actor: User | None,
        config: Settings,
    ) -> PilotManualGateAttestationRead:
        actor = PilotManualGateService._require_actor(
            actor,
            payload.gate_name,
        )
        PilotManualGateService._current_ready_snapshot(
            db,
            config,
            payload.expected_readiness_sha256,
        )
        latest = PilotManualGateRepository.latest_attestation(
            db,
            payload.gate_name,
        )
        if latest is None:
            if (
                payload.supersedes_attestation_id is not None
                or payload.expected_supersedes_sha256 is not None
            ):
                raise PilotManualGateConflictError(
                    "The first attestation cannot supersede another record."
                )
            generation = 1
            supersedes_id = None
        else:
            PilotManualGateService._validate_attestation(latest)
            latest_review = PilotManualGateRepository.get_review_by_attestation(
                db,
                latest.id,
            )
            if latest_review is None:
                raise PilotManualGateConflictError(
                    "The latest attestation is still awaiting independent review."
                )
            PilotManualGateService._validate_review(
                latest_review,
                latest.sha256,
            )
            if (
                payload.supersedes_attestation_id != latest.id
                or payload.expected_supersedes_sha256 != latest.sha256
            ):
                raise PilotManualGateConflictError(
                    "Supersession must reference the latest attestation and hash."
                )
            generation = latest.generation + 1
            supersedes_id = latest.id

        now = datetime.now(timezone.utc)
        attestation_id = str(uuid.uuid4())
        frozen = {
            "schema_version": 1,
            "id": attestation_id,
            "gate_name": payload.gate_name,
            "readiness_sha256": payload.expected_readiness_sha256,
            "generation": generation,
            "release_ref": payload.release_ref.strip(),
            "evidence_reference": payload.evidence_reference.strip(),
            "statement": payload.statement.strip(),
            "supersedes_attestation_id": supersedes_id,
            "attested_by_user_id": actor.id,
            "attested_by_role": actor.role,
            "created_at": now.isoformat(),
            "append_only": True,
            "independent_review_required": True,
            "is_clinical_clearance": False,
            "controlled_pilot_authorized": False,
        }
        sha256 = evidence_digest(frozen)
        try:
            record = PilotManualGateRepository.create_attestation(
                db,
                attestation_id=attestation_id,
                gate_name=payload.gate_name,
                readiness_sha256=payload.expected_readiness_sha256,
                generation=generation,
                release_ref=payload.release_ref.strip(),
                evidence_reference=payload.evidence_reference.strip(),
                statement=payload.statement.strip(),
                supersedes_attestation_id=supersedes_id,
                attested_by_user_id=actor.id,
                attested_by_role=actor.role,
                payload=frozen,
                sha256=sha256,
                created_at=now,
            )
            AuditLogRepository.create(
                db,
                entity_type="pilot_manual_gate_attestation",
                entity_id=record.id,
                event_type="pilot_manual_gate_attested",
                to_state="pending_review",
                event_data={
                    "gate_name": record.gate_name,
                    "generation": record.generation,
                    "readiness_sha256": record.readiness_sha256,
                    "attestation_sha256": record.sha256,
                },
                commit=False,
                **actor_data(actor),
            )
            db.commit()
        except IntegrityError as error:
            db.rollback()
            raise PilotManualGateConflictError(
                "Another attestation changed this gate; reload before retrying."
            ) from error
        except Exception:
            db.rollback()
            raise
        return PilotManualGateService._to_read(db, record)

    @staticmethod
    def review_attestation(
        db: Session,
        attestation_id: str,
        payload: PilotManualGateReviewCreate,
        *,
        actor: User | None,
        config: Settings,
    ) -> PilotManualGateAttestationRead:
        record = PilotManualGateRepository.get_attestation(db, attestation_id)
        if record is None:
            raise PilotManualGateNotFoundError(
                f"Attestation '{attestation_id}' was not found."
            )
        PilotManualGateService._validate_attestation(record)
        actor = PilotManualGateService._require_actor(actor, record.gate_name)
        if actor.id == record.attested_by_user_id:
            raise PilotManualGateAuthorizationError(
                "The attestation author cannot perform its independent review."
            )
        if payload.expected_attestation_sha256 != record.sha256:
            raise PilotManualGateConflictError(
                "The attestation changed; reload before reviewing."
            )
        PilotManualGateService._current_ready_snapshot(
            db,
            config,
            record.readiness_sha256,
        )
        if (
            PilotManualGateRepository.get_review_by_attestation(
                db,
                record.id,
            )
            is not None
        ):
            raise PilotManualGateConflictError(
                "This attestation already has an immutable review."
            )

        now = datetime.now(timezone.utc)
        review_id = str(uuid.uuid4())
        frozen = {
            "schema_version": 1,
            "id": review_id,
            "attestation_id": record.id,
            "attestation_sha256": record.sha256,
            "action": payload.action,
            "rationale": payload.rationale.strip(),
            "reviewed_by_user_id": actor.id,
            "reviewed_by_role": actor.role,
            "created_at": now.isoformat(),
            "independent_review": True,
            "is_clinical_clearance": False,
            "controlled_pilot_authorized": False,
        }
        review_sha256 = evidence_digest(frozen)
        try:
            review = PilotManualGateRepository.create_review(
                db,
                review_id=review_id,
                attestation_id=record.id,
                attestation_sha256=record.sha256,
                action=payload.action,
                rationale=payload.rationale.strip(),
                reviewed_by_user_id=actor.id,
                reviewed_by_role=actor.role,
                payload=frozen,
                sha256=review_sha256,
                created_at=now,
            )
            AuditLogRepository.create(
                db,
                entity_type="pilot_manual_gate_attestation",
                entity_id=record.id,
                event_type="pilot_manual_gate_reviewed",
                from_state="pending_review",
                to_state=(
                    "approved"
                    if review.action == "approve"
                    else "rejected"
                ),
                event_data={
                    "gate_name": record.gate_name,
                    "generation": record.generation,
                    "attestation_sha256": record.sha256,
                    "review_sha256": review.sha256,
                    "action": review.action,
                },
                commit=False,
                **actor_data(actor),
            )
            db.commit()
        except IntegrityError as error:
            db.rollback()
            raise PilotManualGateConflictError(
                "Another review was recorded first; reload this gate."
            ) from error
        except Exception:
            db.rollback()
            raise
        return PilotManualGateService._to_read(db, record)

    @staticmethod
    def get_attestation(
        db: Session,
        attestation_id: str,
    ) -> PilotManualGateAttestationRead:
        record = PilotManualGateRepository.get_attestation(db, attestation_id)
        if record is None:
            raise PilotManualGateNotFoundError(
                f"Attestation '{attestation_id}' was not found."
            )
        return PilotManualGateService._to_read(db, record)

    @staticmethod
    def list_attestations(
        db: Session,
        *,
        gate_name: str | None = None,
    ) -> list[PilotManualGateAttestationRead]:
        return [
            PilotManualGateService._to_read(db, item)
            for item in PilotManualGateRepository.list_attestations(
                db,
                gate_name=gate_name,
            )
        ]

    @staticmethod
    def list_statuses(db: Session) -> list[PilotManualGateStatusRead]:
        statuses = []
        for gate_name in sorted(ALL_GATES):
            latest = PilotManualGateRepository.latest_attestation(
                db,
                gate_name,
            )
            if latest is None:
                statuses.append(
                    PilotManualGateStatusRead(
                        gate_name=gate_name,
                        latest_attestation=None,
                        status="not_attested",
                    )
                )
                continue
            attestation = PilotManualGateService._to_read(db, latest)
            statuses.append(
                PilotManualGateStatusRead(
                    gate_name=gate_name,
                    latest_attestation=attestation,
                    status=attestation.status,
                )
            )
        return statuses

    @staticmethod
    def approved_latest_by_gate(db: Session) -> dict[str, PilotManualGateAttestationRead]:
        result = {}
        for item in PilotManualGateService.list_statuses(db):
            if item.status == "approved" and item.latest_attestation is not None:
                result[item.gate_name] = item.latest_attestation
        return result
