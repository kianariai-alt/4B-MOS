"""Immutable launch package assembled from governed pilot evidence."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.models.user import User
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.repositories.pilot_release import PilotLaunchPackageRepository
from backend.app.schemas.pilot_release import (
    PilotLaunchManifestItem,
    PilotLaunchPackageCreate,
    PilotLaunchPackagePreviewRead,
    PilotLaunchPackageRead,
)
from backend.app.services.audit_context import actor_data
from backend.app.services.pilot_readiness import ControlledPilotReadinessService
from backend.app.services.pilot_release import (
    ALL_GATES,
    PilotManualGateIntegrityError,
    PilotManualGateService,
)
from backend.app.services.session_finalization import evidence_digest


class PilotLaunchPackageNotFoundError(Exception):
    pass


class PilotLaunchPackageConflictError(Exception):
    pass


class PilotLaunchPackageAuthorizationError(Exception):
    pass


class PilotLaunchPackageIntegrityError(Exception):
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


class PilotLaunchPackageService:
    @staticmethod
    def _require_admin(actor: User | None) -> User:
        if actor is None or not actor.is_active or actor.role != "admin":
            raise PilotLaunchPackageAuthorizationError(
                "Only an active administrator may freeze a launch package."
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
                and raw.get("release_ref") == record.release_ref
                and raw.get("readiness_sha256") == record.readiness_sha256
                and raw.get("attestation_manifest")
                == list(record.attestation_manifest)
                and raw.get("created_by_user_id")
                == record.created_by_user_id
                and _same_timestamp(raw.get("created_at"), record.created_at)
                and raw.get("append_only") is True
                and raw.get("controlled_pilot_authorized") is False
                and raw.get("is_clinical_clearance") is False
                and raw.get("requires_human_release_decision") is True
            )
        except (AttributeError, TypeError, ValueError):
            valid = False
        if not valid:
            raise PilotLaunchPackageIntegrityError(
                "Stored pilot launch package failed its integrity check."
            )
        return raw

    @staticmethod
    def _to_read(record) -> PilotLaunchPackageRead:
        PilotLaunchPackageService._validate(record)
        return PilotLaunchPackageRead(
            id=record.id,
            release_ref=record.release_ref,
            readiness_sha256=record.readiness_sha256,
            attestation_manifest=[
                PilotLaunchManifestItem.model_validate(item)
                for item in record.attestation_manifest
            ],
            created_by_user_id=record.created_by_user_id,
            sha256=record.sha256,
            created_at=record.created_at,
        )

    @staticmethod
    def preview(
        db: Session,
        config: Settings,
    ) -> PilotLaunchPackagePreviewRead:
        readiness = ControlledPilotReadinessService.build(db, config)
        issues: list[str] = []
        if readiness.status != "automated_prerequisites_passed":
            issues.append("automated_prerequisites_not_passing")

        try:
            statuses = PilotManualGateService.list_statuses(db)
        except PilotManualGateIntegrityError as error:
            raise PilotLaunchPackageIntegrityError(str(error)) from error

        by_gate = {item.gate_name: item for item in statuses}
        manifest: list[PilotLaunchManifestItem] = []
        release_refs: set[str] = set()
        approved_count = 0

        for gate_name in sorted(ALL_GATES):
            state = by_gate.get(gate_name)
            if (
                state is None
                or state.latest_attestation is None
                or state.status != "approved"
            ):
                issues.append(f"manual_gate_not_approved:{gate_name}")
                continue

            latest = state.latest_attestation
            approved_count += 1
            if latest.readiness_sha256 != readiness.readiness_sha256:
                issues.append(f"manual_gate_stale_readiness:{gate_name}")
                continue
            if latest.review is None or latest.review.action != "approve":
                issues.append(f"manual_gate_review_invalid:{gate_name}")
                continue

            release_refs.add(latest.release_ref)
            manifest.append(
                PilotLaunchManifestItem(
                    gate_name=gate_name,
                    generation=latest.generation,
                    attestation_id=latest.id,
                    attestation_sha256=latest.sha256,
                    review_id=latest.review.id,
                    review_sha256=latest.review.sha256,
                )
            )

        release_ref = next(iter(release_refs)) if len(release_refs) == 1 else None
        if len(release_refs) > 1:
            issues.append("manual_gate_release_ref_mismatch")
        if len(manifest) != len(ALL_GATES):
            if "manual_gate_manifest_incomplete" not in issues:
                issues.append("manual_gate_manifest_incomplete")
        if (
            release_ref is not None
            and PilotLaunchPackageRepository.get_by_release_ref(
                db,
                release_ref,
            )
            is not None
        ):
            issues.append("launch_package_already_exists")

        return PilotLaunchPackagePreviewRead(
            status="packageable" if not issues else "blocked",
            readiness_sha256=readiness.readiness_sha256,
            release_ref=release_ref,
            approved_gate_count=approved_count,
            issues=issues,
            attestation_manifest=manifest,
        )

    @staticmethod
    def create(
        db: Session,
        payload: PilotLaunchPackageCreate,
        *,
        actor: User | None,
        config: Settings,
    ) -> PilotLaunchPackageRead:
        actor = PilotLaunchPackageService._require_admin(actor)
        preview = PilotLaunchPackageService.preview(db, config)
        if preview.status != "packageable":
            raise PilotLaunchPackageConflictError(
                "Pilot launch evidence is not currently packageable."
            )
        if payload.expected_readiness_sha256 != preview.readiness_sha256:
            raise PilotLaunchPackageConflictError(
                "Pilot readiness changed; reload the package preview."
            )
        if payload.expected_release_ref != preview.release_ref:
            raise PilotLaunchPackageConflictError(
                "Manual gate release reference changed; reload the preview."
            )

        expected = {
            item.gate_name: item.attestation_sha256
            for item in payload.expected_attestations
        }
        if len(expected) != len(ALL_GATES):
            raise PilotLaunchPackageConflictError(
                "Expected attestations must contain each manual gate exactly once."
            )
        current = {
            item.gate_name: item.attestation_sha256
            for item in preview.attestation_manifest
        }
        if expected != current:
            raise PilotLaunchPackageConflictError(
                "Manual gate evidence changed; reload the package preview."
            )

        now = datetime.now(timezone.utc)
        package_id = str(uuid.uuid4())
        manifest = [
            item.model_dump(mode="json")
            for item in preview.attestation_manifest
        ]
        frozen = {
            "schema_version": 1,
            "id": package_id,
            "release_ref": preview.release_ref,
            "readiness_sha256": preview.readiness_sha256,
            "attestation_manifest": manifest,
            "created_by_user_id": actor.id,
            "created_at": now.isoformat(),
            "append_only": True,
            "controlled_pilot_authorized": False,
            "is_clinical_clearance": False,
            "requires_human_release_decision": True,
        }
        sha256 = evidence_digest(frozen)

        try:
            record = PilotLaunchPackageRepository.create(
                db,
                package_id=package_id,
                release_ref=preview.release_ref,
                readiness_sha256=preview.readiness_sha256,
                attestation_manifest=manifest,
                created_by_user_id=actor.id,
                payload=frozen,
                sha256=sha256,
                created_at=now,
            )
            AuditLogRepository.create(
                db,
                entity_type="pilot_launch_package",
                entity_id=record.id,
                event_type="pilot_launch_package_frozen",
                to_state="awaiting_human_release_decision",
                event_data={
                    "release_ref": record.release_ref,
                    "readiness_sha256": record.readiness_sha256,
                    "package_sha256": record.sha256,
                    "manual_gate_count": len(manifest),
                },
                commit=False,
                **actor_data(actor),
            )
            db.commit()
        except IntegrityError as error:
            db.rollback()
            raise PilotLaunchPackageConflictError(
                "A launch package for this release already exists."
            ) from error
        except Exception:
            db.rollback()
            raise
        return PilotLaunchPackageService._to_read(record)

    @staticmethod
    def get(
        db: Session,
        package_id: str,
    ) -> PilotLaunchPackageRead:
        record = PilotLaunchPackageRepository.get(db, package_id)
        if record is None:
            raise PilotLaunchPackageNotFoundError(
                f"Pilot launch package '{package_id}' was not found."
            )
        return PilotLaunchPackageService._to_read(record)

    @staticmethod
    def list(db: Session) -> list[PilotLaunchPackageRead]:
        return [
            PilotLaunchPackageService._to_read(item)
            for item in PilotLaunchPackageRepository.list(db)
        ]
