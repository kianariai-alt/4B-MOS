from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.pilot_release import (
    PilotManualGateAttestation,
    PilotManualGateReview,
    PilotLaunchPackage,
)


class PilotManualGateRepository:
    @staticmethod
    def get_attestation(
        db: Session,
        attestation_id: str,
    ) -> PilotManualGateAttestation | None:
        return db.get(PilotManualGateAttestation, attestation_id)

    @staticmethod
    def get_review_by_attestation(
        db: Session,
        attestation_id: str,
    ) -> PilotManualGateReview | None:
        return db.scalar(
            select(PilotManualGateReview).where(
                PilotManualGateReview.attestation_id == attestation_id
            )
        )

    @staticmethod
    def list_attestations(
        db: Session,
        *,
        gate_name: str | None = None,
    ) -> list[PilotManualGateAttestation]:
        statement = select(PilotManualGateAttestation)
        if gate_name is not None:
            statement = statement.where(
                PilotManualGateAttestation.gate_name == gate_name
            )
        statement = statement.order_by(
            PilotManualGateAttestation.created_at.asc(),
            PilotManualGateAttestation.id.asc(),
        )
        return list(db.scalars(statement).all())

    @staticmethod
    def latest_attestation(
        db: Session,
        gate_name: str,
    ) -> PilotManualGateAttestation | None:
        return db.scalar(
            select(PilotManualGateAttestation)
            .where(PilotManualGateAttestation.gate_name == gate_name)
            .order_by(
                PilotManualGateAttestation.created_at.desc(),
                PilotManualGateAttestation.id.desc(),
            )
            .limit(1)
        )

    @staticmethod
    def create_attestation(
        db: Session,
        *,
        attestation_id: str,
        gate_name: str,
        readiness_sha256: str,
        generation: int,
        release_ref: str,
        evidence_reference: str,
        statement: str,
        supersedes_attestation_id: str | None,
        attested_by_user_id: str,
        attested_by_role: str,
        payload: dict,
        sha256: str,
        created_at,
    ) -> PilotManualGateAttestation:
        record = PilotManualGateAttestation(
            id=attestation_id,
            gate_name=gate_name,
            readiness_sha256=readiness_sha256,
            generation=generation,
            release_ref=release_ref,
            evidence_reference=evidence_reference,
            statement=statement,
            supersedes_attestation_id=supersedes_attestation_id,
            attested_by_user_id=attested_by_user_id,
            attested_by_role=attested_by_role,
            payload=payload,
            sha256=sha256,
            created_at=created_at,
        )
        db.add(record)
        db.flush()
        db.refresh(record)
        return record

    @staticmethod
    def create_review(
        db: Session,
        *,
        review_id: str,
        attestation_id: str,
        attestation_sha256: str,
        action: str,
        rationale: str,
        reviewed_by_user_id: str,
        reviewed_by_role: str,
        payload: dict,
        sha256: str,
        created_at,
    ) -> PilotManualGateReview:
        record = PilotManualGateReview(
            id=review_id,
            attestation_id=attestation_id,
            attestation_sha256=attestation_sha256,
            action=action,
            rationale=rationale,
            reviewed_by_user_id=reviewed_by_user_id,
            reviewed_by_role=reviewed_by_role,
            payload=payload,
            sha256=sha256,
            created_at=created_at,
        )
        db.add(record)
        db.flush()
        db.refresh(record)
        return record



class PilotLaunchPackageRepository:
    @staticmethod
    def get(
        db: Session,
        package_id: str,
    ) -> PilotLaunchPackage | None:
        return db.get(PilotLaunchPackage, package_id)

    @staticmethod
    def get_by_release_ref(
        db: Session,
        release_ref: str,
    ) -> PilotLaunchPackage | None:
        return db.scalar(
            select(PilotLaunchPackage).where(
                PilotLaunchPackage.release_ref == release_ref
            )
        )

    @staticmethod
    def list(db: Session) -> list[PilotLaunchPackage]:
        return list(
            db.scalars(
                select(PilotLaunchPackage).order_by(
                    PilotLaunchPackage.created_at.asc(),
                    PilotLaunchPackage.id.asc(),
                )
            ).all()
        )

    @staticmethod
    def create(
        db: Session,
        *,
        package_id: str,
        release_ref: str,
        readiness_sha256: str,
        attestation_manifest: list[dict],
        created_by_user_id: str,
        payload: dict,
        sha256: str,
        created_at,
    ) -> PilotLaunchPackage:
        record = PilotLaunchPackage(
            id=package_id,
            release_ref=release_ref,
            readiness_sha256=readiness_sha256,
            attestation_manifest=list(attestation_manifest),
            created_by_user_id=created_by_user_id,
            payload=payload,
            sha256=sha256,
            created_at=created_at,
        )
        db.add(record)
        db.flush()
        db.refresh(record)
        return record
