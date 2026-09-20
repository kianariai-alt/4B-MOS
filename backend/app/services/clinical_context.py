from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from backend.app.db.clinical_record_transactions import clinical_record_write
from backend.app.models.audit_log import AuditLog
from backend.app.models.clinical_context import (
    ClinicalIntake,
    ParaclinicalObservation,
    ParaclinicalReport,
)
from backend.app.models.user import User
from backend.app.models.visit import Visit
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.repositories.clinical_context import ClinicalContextRepository
from backend.app.repositories.visit import VisitRepository
from backend.app.schemas.clinical_context import (
    ClinicalContextRead,
    ClinicalIntakeContent,
    ClinicalIntakeCreate,
    ClinicalIntakeRead,
    ClinicalIntakeSupersede,
    EnterClinicalRecordInError,
    ParaclinicalObservationInput,
    ParaclinicalObservationRead,
    ParaclinicalReportContent,
    ParaclinicalReportCreate,
    ParaclinicalReportRead,
    ParaclinicalReportSupersede,
)
from backend.app.services.audit_context import actor_data


AUTHOR_ROLES = {"admin", "physician", "nurse", "operator"}
FINALIZE_ROLES = {"admin", "physician"}


class ClinicalContextNotFoundError(Exception):
    pass


class ClinicalContextConflictError(Exception):
    pass


class ClinicalContextAuthorizationError(Exception):
    pass


class ClinicalContextIntegrityError(Exception):
    pass


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _datetime_text(value: datetime | None) -> str | None:
    normalized = _utc(value)
    if normalized is None:
        return None
    return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    normalized = value.normalize()
    if normalized == 0:
        return "0"
    return format(normalized, "f")


def _observation_payload(observation: ParaclinicalObservationInput) -> dict:
    return {
        "category": observation.category,
        "code_system": observation.code_system,
        "code_system_uri": observation.code_system_uri,
        "code_system_version": observation.code_system_version,
        "code": observation.code,
        "display_name": observation.display_name,
        "value_type": observation.value_type,
        "quantity_value": _decimal_text(observation.quantity_value),
        "string_value": observation.string_value,
        "boolean_value": observation.boolean_value,
        "integer_value": observation.integer_value,
        "coded_value": observation.coded_value,
        "coded_system": observation.coded_system,
        "coded_display": observation.coded_display,
        "datetime_value": _datetime_text(observation.datetime_value),
        "absent_reason": observation.absent_reason,
        "unit_code": observation.unit_code,
        "unit_display": observation.unit_display,
        "reference_low": _decimal_text(observation.reference_low),
        "reference_high": _decimal_text(observation.reference_high),
        "reference_text": observation.reference_text,
        "interpretation": observation.interpretation,
        "body_site": observation.body_site,
        "specimen": observation.specimen,
        "method": observation.method,
        "note": observation.note,
        "observed_at": _datetime_text(observation.observed_at),
    }


def _digest(payload: dict) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def clinical_intake_digest(
    *,
    visit_id: str,
    version: int,
    content: ClinicalIntakeContent,
    supersedes_intake_id: str | None,
    revision_reason: str | None,
) -> str:
    payload = {
        "schema_version": 1,
        "record_type": "clinical_intake",
        "visit_id": visit_id,
        "version": version,
        "supersedes_intake_id": supersedes_intake_id,
        "revision_reason": revision_reason,
        **content.model_dump(mode="json"),
    }
    return _digest(payload)


def paraclinical_report_digest(
    *,
    visit_id: str,
    report_key: str,
    version: int,
    content: ParaclinicalReportContent,
    supersedes_report_id: str | None,
    revision_reason: str | None,
) -> str:
    payload = {
        "schema_version": 1,
        "record_type": "paraclinical_report",
        "visit_id": visit_id,
        "report_key": report_key,
        "version": version,
        "supersedes_report_id": supersedes_report_id,
        "revision_reason": revision_reason,
        "category": content.category,
        "title": content.title,
        "external_identifier": content.external_identifier,
        "performed_at": _datetime_text(content.performed_at),
        "issued_at": _datetime_text(content.issued_at),
        "performer": content.performer,
        "conclusion": content.conclusion,
        "source_reference": content.source_reference,
        "observations": [
            _observation_payload(observation)
            for observation in content.observations
        ],
    }
    return _digest(payload)


class ClinicalContextService:
    @staticmethod
    def _require_actor(actor: User | None, allowed_roles: set[str]) -> User:
        if (
            actor is None
            or not actor.is_active
            or actor.role not in allowed_roles
        ):
            raise ClinicalContextAuthorizationError(
                "The current role is not allowed to perform this clinical action."
            )
        return actor

    @staticmethod
    def _require_visit(db: Session, visit_id: str) -> Visit:
        visit = VisitRepository.get_by_id(db, visit_id)
        if visit is None:
            raise ClinicalContextNotFoundError(
                f"Visit '{visit_id}' was not found."
            )
        return visit

    @staticmethod
    def _require_intake(
        db: Session,
        intake_id: str,
        *,
        for_update: bool = False,
    ) -> ClinicalIntake:
        intake = ClinicalContextRepository.get_intake_by_id(
            db,
            intake_id,
            for_update=for_update,
        )
        if intake is None:
            raise ClinicalContextNotFoundError(
                f"Clinical intake '{intake_id}' was not found."
            )
        return intake

    @staticmethod
    def _require_report(
        db: Session,
        report_id: str,
        *,
        for_update: bool = False,
    ) -> ParaclinicalReport:
        report = ClinicalContextRepository.get_report_by_id(
            db,
            report_id,
            for_update=for_update,
        )
        if report is None:
            raise ClinicalContextNotFoundError(
                f"Paraclinical report '{report_id}' was not found."
            )
        return report

    @staticmethod
    def _intake_content(record: ClinicalIntake) -> ClinicalIntakeContent:
        return ClinicalIntakeContent(
            chief_complaint=record.chief_complaint,
            history_present_illness=record.history_present_illness,
            body_region=record.body_region,
            laterality=record.laterality,
            symptom_onset_date=record.symptom_onset_date,
            pain_score=record.pain_score,
            functional_limitations=list(record.functional_limitations),
            relevant_history=list(record.relevant_history),
            current_medications=list(record.current_medications),
            allergies=list(record.allergies),
            exam_findings=record.exam_findings,
            red_flags=list(record.red_flags),
            clinical_impression=record.clinical_impression,
            care_goal=record.care_goal,
        )

    @staticmethod
    def _observation_content(
        record: ParaclinicalObservation,
    ) -> ParaclinicalObservationInput:
        return ParaclinicalObservationInput(
            category=record.category,
            code_system=record.code_system,
            code_system_uri=record.code_system_uri,
            code_system_version=record.code_system_version,
            code=record.code,
            display_name=record.display_name,
            value_type=record.value_type,
            quantity_value=record.quantity_value,
            string_value=record.string_value,
            boolean_value=record.boolean_value,
            integer_value=record.integer_value,
            coded_value=record.coded_value,
            coded_system=record.coded_system,
            coded_display=record.coded_display,
            datetime_value=_utc(record.datetime_value),
            absent_reason=record.absent_reason,
            unit_code=record.unit_code,
            unit_display=record.unit_display,
            reference_low=record.reference_low,
            reference_high=record.reference_high,
            reference_text=record.reference_text,
            interpretation=record.interpretation,
            body_site=record.body_site,
            specimen=record.specimen,
            method=record.method,
            note=record.note,
            observed_at=_utc(record.observed_at),
        )

    @staticmethod
    def _report_content(record: ParaclinicalReport) -> ParaclinicalReportContent:
        return ParaclinicalReportContent(
            category=record.category,
            title=record.title,
            external_identifier=record.external_identifier,
            performed_at=_utc(record.performed_at),
            issued_at=_utc(record.issued_at),
            performer=record.performer,
            conclusion=record.conclusion,
            source_reference=record.source_reference,
            observations=[
                ClinicalContextService._observation_content(observation)
                for observation in record.observations
            ],
        )

    @staticmethod
    def _verify_intake(record: ClinicalIntake) -> None:
        expected = clinical_intake_digest(
            visit_id=record.visit_id,
            version=record.version,
            content=ClinicalContextService._intake_content(record),
            supersedes_intake_id=record.supersedes_intake_id,
            revision_reason=record.revision_reason,
        )
        if expected != record.content_sha256:
            raise ClinicalContextIntegrityError(
                "Stored clinical intake failed its integrity check."
            )

    @staticmethod
    def _verify_report(record: ParaclinicalReport) -> None:
        expected = paraclinical_report_digest(
            visit_id=record.visit_id,
            report_key=record.report_key,
            version=record.version,
            content=ClinicalContextService._report_content(record),
            supersedes_report_id=record.supersedes_report_id,
            revision_reason=record.revision_reason,
        )
        if expected != record.content_sha256:
            raise ClinicalContextIntegrityError(
                "Stored paraclinical report failed its integrity check."
            )

    @staticmethod
    def _intake_read(record: ClinicalIntake) -> ClinicalIntakeRead:
        ClinicalContextService._verify_intake(record)
        return ClinicalIntakeRead.model_validate(record)

    @staticmethod
    def _report_read(record: ParaclinicalReport) -> ParaclinicalReportRead:
        content = ClinicalContextService._report_content(record)
        ClinicalContextService._verify_report(record)
        observations = [
            ParaclinicalObservationRead(
                **ClinicalContextService._observation_content(observation).model_dump(),
                id=observation.id,
                sort_order=observation.sort_order,
                created_at=observation.created_at,
            )
            for observation in record.observations
        ]
        return ParaclinicalReportRead(
            **content.model_dump(exclude={"observations"}),
            observations=observations,
            id=record.id,
            visit_id=record.visit_id,
            report_key=record.report_key,
            version=record.version,
            status=record.status,
            revision_reason=record.revision_reason,
            content_sha256=record.content_sha256,
            supersedes_report_id=record.supersedes_report_id,
            created_by_user_id=record.created_by_user_id,
            finalized_by_user_id=record.finalized_by_user_id,
            finalized_at=record.finalized_at,
            entered_in_error_by_user_id=record.entered_in_error_by_user_id,
            entered_in_error_at=record.entered_in_error_at,
            error_reason=record.error_reason,
            row_version=record.row_version,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _audit(
        db: Session,
        *,
        entity_type: str,
        entity_id: str,
        event_type: str,
        actor: User,
        from_state: str | None,
        to_state: str | None,
        message: str,
        event_data: dict,
    ) -> None:
        AuditLogRepository.create(
            db,
            commit=False,
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            from_state=from_state,
            to_state=to_state,
            message=message,
            event_data=event_data,
            **actor_data(actor),
        )

    @staticmethod
    @clinical_record_write
    def create_intake(
        db: Session,
        visit_id: str,
        payload: ClinicalIntakeCreate,
        *,
        actor: User | None,
    ) -> ClinicalIntakeRead:
        actor = ClinicalContextService._require_actor(actor, AUTHOR_ROLES)
        visit = ClinicalContextService._require_visit(db, visit_id)
        if visit.status != "open":
            raise ClinicalContextConflictError(
                "A first clinical intake can only be created for an open visit."
            )
        if ClinicalContextRepository.get_latest_intake(db, visit_id) is not None:
            raise ClinicalContextConflictError(
                "This visit already has a clinical intake lineage."
            )
        content = ClinicalIntakeContent.model_validate(payload.model_dump())
        digest = clinical_intake_digest(
            visit_id=visit_id,
            version=1,
            content=content,
            supersedes_intake_id=None,
            revision_reason=None,
        )
        intake = ClinicalContextRepository.create_intake(
            db,
            visit_id=visit_id,
            version=1,
            content=content,
            content_sha256=digest,
            created_by_user_id=actor.id,
        )
        ClinicalContextService._audit(
            db,
            entity_type="clinical_intake",
            entity_id=intake.id,
            event_type="clinical_intake_created",
            actor=actor,
            from_state=None,
            to_state="draft",
            message="Structured clinical intake created as draft.",
            event_data={
                "visit_id": visit_id,
                "version": 1,
                "content_sha256": digest,
            },
        )
        return ClinicalContextService._intake_read(intake)

    @staticmethod
    def get_intake(db: Session, intake_id: str) -> ClinicalIntakeRead:
        return ClinicalContextService._intake_read(
            ClinicalContextService._require_intake(db, intake_id)
        )

    @staticmethod
    def list_intakes(db: Session, visit_id: str) -> list[ClinicalIntakeRead]:
        ClinicalContextService._require_visit(db, visit_id)
        return [
            ClinicalContextService._intake_read(record)
            for record in ClinicalContextRepository.list_intakes(db, visit_id)
        ]

    @staticmethod
    @clinical_record_write
    def update_intake(
        db: Session,
        intake_id: str,
        payload: ClinicalIntakeContent,
        *,
        actor: User | None,
    ) -> ClinicalIntakeRead:
        actor = ClinicalContextService._require_actor(actor, AUTHOR_ROLES)
        intake = ClinicalContextService._require_intake(
            db,
            intake_id,
            for_update=True,
        )
        ClinicalContextService._verify_intake(intake)
        if intake.status != "draft":
            raise ClinicalContextConflictError(
                "Only a draft clinical intake can be edited."
            )
        visit = ClinicalContextService._require_visit(db, intake.visit_id)
        if intake.version == 1 and visit.status != "open":
            raise ClinicalContextConflictError(
                "The first intake draft cannot be edited after the visit closes."
            )
        for field, value in payload.model_dump().items():
            setattr(intake, field, value)
        intake.content_sha256 = clinical_intake_digest(
            visit_id=intake.visit_id,
            version=intake.version,
            content=payload,
            supersedes_intake_id=intake.supersedes_intake_id,
            revision_reason=intake.revision_reason,
        )
        ClinicalContextService._audit(
            db,
            entity_type="clinical_intake",
            entity_id=intake.id,
            event_type="clinical_intake_updated",
            actor=actor,
            from_state="draft",
            to_state="draft",
            message="Structured clinical intake draft replaced.",
            event_data={
                "visit_id": intake.visit_id,
                "version": intake.version,
                "content_sha256": intake.content_sha256,
            },
        )
        return ClinicalContextService._intake_read(intake)

    @staticmethod
    @clinical_record_write
    def finalize_intake(
        db: Session,
        intake_id: str,
        *,
        actor: User | None,
    ) -> ClinicalIntakeRead:
        actor = ClinicalContextService._require_actor(actor, FINALIZE_ROLES)
        intake = ClinicalContextService._require_intake(
            db,
            intake_id,
            for_update=True,
        )
        ClinicalContextService._verify_intake(intake)
        if intake.status != "draft":
            raise ClinicalContextConflictError(
                "Only a draft clinical intake can be finalized."
            )
        visit = ClinicalContextService._require_visit(db, intake.visit_id)
        if intake.version == 1 and visit.status != "open":
            raise ClinicalContextConflictError(
                "The first intake draft cannot be finalized after the visit closes."
            )
        now = datetime.now(timezone.utc)
        if intake.supersedes_intake_id is not None:
            previous = ClinicalContextService._require_intake(
                db,
                intake.supersedes_intake_id,
                for_update=True,
            )
            ClinicalContextService._verify_intake(previous)
            if previous.status not in {"final", "entered_in_error"}:
                raise ClinicalContextConflictError(
                    "The intake being corrected cannot accept a finalized replacement."
                )
            previous_state = previous.status
            if previous_state == "final":
                previous.status = "superseded"
            ClinicalContextService._audit(
                db,
                entity_type="clinical_intake",
                entity_id=previous.id,
                event_type=(
                    "clinical_intake_superseded"
                    if previous_state == "final"
                    else "clinical_intake_error_replaced"
                ),
                actor=actor,
                from_state=("final" if previous_state == "final" else None),
                to_state=("superseded" if previous_state == "final" else None),
                message=(
                    "Clinical intake replaced by a finalized correction."
                    if previous_state == "final"
                    else "A replacement for an entered-in-error intake was finalized."
                ),
                event_data={
                    "visit_id": previous.visit_id,
                    "version": previous.version,
                    "successor_intake_id": intake.id,
                    "content_sha256": previous.content_sha256,
                },
            )
        intake.status = "final"
        intake.finalized_by_user_id = actor.id
        intake.finalized_at = now
        ClinicalContextService._audit(
            db,
            entity_type="clinical_intake",
            entity_id=intake.id,
            event_type="clinical_intake_finalized",
            actor=actor,
            from_state="draft",
            to_state="final",
            message="Structured clinical intake finalized.",
            event_data={
                "visit_id": intake.visit_id,
                "version": intake.version,
                "content_sha256": intake.content_sha256,
            },
        )
        return ClinicalContextService._intake_read(intake)

    @staticmethod
    @clinical_record_write
    def supersede_intake(
        db: Session,
        intake_id: str,
        payload: ClinicalIntakeSupersede,
        *,
        actor: User | None,
    ) -> ClinicalIntakeRead:
        actor = ClinicalContextService._require_actor(actor, AUTHOR_ROLES)
        previous = ClinicalContextService._require_intake(
            db,
            intake_id,
            for_update=True,
        )
        ClinicalContextService._verify_intake(previous)
        if previous.status not in {"final", "entered_in_error"}:
            raise ClinicalContextConflictError(
                "Only a current final or entered-in-error clinical intake "
                "can receive a replacement."
            )
        if ClinicalContextRepository.get_intake_successor(db, previous.id) is not None:
            raise ClinicalContextConflictError(
                "A correction already exists for this clinical intake."
            )
        content = ClinicalIntakeContent.model_validate(
            payload.model_dump(exclude={"revision_reason"})
        )
        version = previous.version + 1
        digest = clinical_intake_digest(
            visit_id=previous.visit_id,
            version=version,
            content=content,
            supersedes_intake_id=previous.id,
            revision_reason=payload.revision_reason,
        )
        replacement = ClinicalContextRepository.create_intake(
            db,
            visit_id=previous.visit_id,
            version=version,
            content=content,
            content_sha256=digest,
            created_by_user_id=actor.id,
            supersedes_intake_id=previous.id,
            revision_reason=payload.revision_reason,
        )
        ClinicalContextService._audit(
            db,
            entity_type="clinical_intake",
            entity_id=replacement.id,
            event_type="clinical_intake_correction_created",
            actor=actor,
            from_state=None,
            to_state="draft",
            message="Correcting clinical intake version created as draft.",
            event_data={
                "visit_id": replacement.visit_id,
                "version": replacement.version,
                "supersedes_intake_id": previous.id,
                "content_sha256": replacement.content_sha256,
            },
        )
        return ClinicalContextService._intake_read(replacement)

    @staticmethod
    @clinical_record_write
    def enter_intake_in_error(
        db: Session,
        intake_id: str,
        payload: EnterClinicalRecordInError,
        *,
        actor: User | None,
    ) -> ClinicalIntakeRead:
        actor = ClinicalContextService._require_actor(actor, FINALIZE_ROLES)
        intake = ClinicalContextService._require_intake(
            db,
            intake_id,
            for_update=True,
        )
        ClinicalContextService._verify_intake(intake)
        if intake.status != "final":
            raise ClinicalContextConflictError(
                "Only a current final clinical intake can be entered in error."
            )
        if ClinicalContextRepository.get_intake_successor(db, intake.id) is not None:
            raise ClinicalContextConflictError(
                "This clinical intake already has a correction."
            )
        intake.status = "entered_in_error"
        intake.entered_in_error_by_user_id = actor.id
        intake.entered_in_error_at = datetime.now(timezone.utc)
        intake.error_reason = payload.reason
        ClinicalContextService._audit(
            db,
            entity_type="clinical_intake",
            entity_id=intake.id,
            event_type="clinical_intake_entered_in_error",
            actor=actor,
            from_state="final",
            to_state="entered_in_error",
            message="Clinical intake marked as entered in error.",
            event_data={
                "visit_id": intake.visit_id,
                "version": intake.version,
                "content_sha256": intake.content_sha256,
                "reason_recorded": True,
            },
        )
        return ClinicalContextService._intake_read(intake)

    @staticmethod
    def list_intake_audit_logs(
        db: Session,
        intake_id: str,
    ) -> list[AuditLog]:
        intake = ClinicalContextService._require_intake(db, intake_id)
        ClinicalContextService._verify_intake(intake)
        return AuditLogRepository.list_by_entity(
            db,
            entity_type="clinical_intake",
            entity_id=intake_id,
        )

    @staticmethod
    @clinical_record_write
    def create_report(
        db: Session,
        visit_id: str,
        payload: ParaclinicalReportCreate,
        *,
        actor: User | None,
    ) -> ParaclinicalReportRead:
        actor = ClinicalContextService._require_actor(actor, AUTHOR_ROLES)
        visit = ClinicalContextService._require_visit(db, visit_id)
        if visit.status == "cancelled":
            raise ClinicalContextConflictError(
                "A paraclinical report cannot be added to a cancelled visit."
            )
        if ClinicalContextRepository.get_latest_report(
            db,
            visit_id=visit_id,
            report_key=payload.report_key,
        ) is not None:
            raise ClinicalContextConflictError(
                f"Report key '{payload.report_key}' already exists for this visit; "
                "create a superseding version."
            )
        content = ParaclinicalReportContent.model_validate(
            payload.model_dump(exclude={"report_key"})
        )
        digest = paraclinical_report_digest(
            visit_id=visit_id,
            report_key=payload.report_key,
            version=1,
            content=content,
            supersedes_report_id=None,
            revision_reason=None,
        )
        report = ClinicalContextRepository.create_report(
            db,
            visit_id=visit_id,
            report_key=payload.report_key,
            version=1,
            content=content,
            content_sha256=digest,
            created_by_user_id=actor.id,
        )
        ClinicalContextService._audit(
            db,
            entity_type="paraclinical_report",
            entity_id=report.id,
            event_type="paraclinical_report_created",
            actor=actor,
            from_state=None,
            to_state="draft",
            message="Structured paraclinical report created as draft.",
            event_data={
                "visit_id": visit_id,
                "report_key": report.report_key,
                "version": 1,
                "observation_count": len(report.observations),
                "content_sha256": digest,
            },
        )
        return ClinicalContextService._report_read(report)

    @staticmethod
    def get_report(db: Session, report_id: str) -> ParaclinicalReportRead:
        return ClinicalContextService._report_read(
            ClinicalContextService._require_report(db, report_id)
        )

    @staticmethod
    def list_reports(
        db: Session,
        visit_id: str,
        *,
        report_key: str | None = None,
    ) -> list[ParaclinicalReportRead]:
        ClinicalContextService._require_visit(db, visit_id)
        normalized_key = report_key.upper() if report_key is not None else None
        return [
            ClinicalContextService._report_read(record)
            for record in ClinicalContextRepository.list_reports(
                db,
                visit_id,
                report_key=normalized_key,
            )
        ]

    @staticmethod
    @clinical_record_write
    def update_report(
        db: Session,
        report_id: str,
        payload: ParaclinicalReportContent,
        *,
        actor: User | None,
    ) -> ParaclinicalReportRead:
        actor = ClinicalContextService._require_actor(actor, AUTHOR_ROLES)
        report = ClinicalContextService._require_report(
            db,
            report_id,
            for_update=True,
        )
        ClinicalContextService._verify_report(report)
        if report.status != "draft":
            raise ClinicalContextConflictError(
                "Only a draft paraclinical report can be edited."
            )
        for field, value in payload.model_dump(exclude={"observations"}).items():
            setattr(report, field, value)
        ClinicalContextRepository.replace_observations(
            db,
            report,
            payload.observations,
        )
        report.content_sha256 = paraclinical_report_digest(
            visit_id=report.visit_id,
            report_key=report.report_key,
            version=report.version,
            content=payload,
            supersedes_report_id=report.supersedes_report_id,
            revision_reason=report.revision_reason,
        )
        ClinicalContextService._audit(
            db,
            entity_type="paraclinical_report",
            entity_id=report.id,
            event_type="paraclinical_report_updated",
            actor=actor,
            from_state="draft",
            to_state="draft",
            message="Structured paraclinical report draft replaced.",
            event_data={
                "visit_id": report.visit_id,
                "report_key": report.report_key,
                "version": report.version,
                "observation_count": len(report.observations),
                "content_sha256": report.content_sha256,
            },
        )
        return ClinicalContextService._report_read(report)

    @staticmethod
    @clinical_record_write
    def finalize_report(
        db: Session,
        report_id: str,
        *,
        actor: User | None,
    ) -> ParaclinicalReportRead:
        actor = ClinicalContextService._require_actor(actor, FINALIZE_ROLES)
        report = ClinicalContextService._require_report(
            db,
            report_id,
            for_update=True,
        )
        ClinicalContextService._verify_report(report)
        if report.status != "draft":
            raise ClinicalContextConflictError(
                "Only a draft paraclinical report can be finalized."
            )
        now = datetime.now(timezone.utc)
        if report.supersedes_report_id is not None:
            previous = ClinicalContextService._require_report(
                db,
                report.supersedes_report_id,
                for_update=True,
            )
            ClinicalContextService._verify_report(previous)
            if previous.status not in {"final", "entered_in_error"}:
                raise ClinicalContextConflictError(
                    "The report being corrected cannot accept a finalized replacement."
                )
            previous_state = previous.status
            if previous_state == "final":
                previous.status = "superseded"
            ClinicalContextService._audit(
                db,
                entity_type="paraclinical_report",
                entity_id=previous.id,
                event_type=(
                    "paraclinical_report_superseded"
                    if previous_state == "final"
                    else "paraclinical_report_error_replaced"
                ),
                actor=actor,
                from_state=("final" if previous_state == "final" else None),
                to_state=("superseded" if previous_state == "final" else None),
                message=(
                    "Paraclinical report replaced by a finalized correction."
                    if previous_state == "final"
                    else "A replacement for an entered-in-error report was finalized."
                ),
                event_data={
                    "visit_id": previous.visit_id,
                    "report_key": previous.report_key,
                    "version": previous.version,
                    "successor_report_id": report.id,
                    "content_sha256": previous.content_sha256,
                },
            )
        report.status = "final"
        report.finalized_by_user_id = actor.id
        report.finalized_at = now
        ClinicalContextService._audit(
            db,
            entity_type="paraclinical_report",
            entity_id=report.id,
            event_type="paraclinical_report_finalized",
            actor=actor,
            from_state="draft",
            to_state="final",
            message="Structured paraclinical report finalized.",
            event_data={
                "visit_id": report.visit_id,
                "report_key": report.report_key,
                "version": report.version,
                "observation_count": len(report.observations),
                "content_sha256": report.content_sha256,
            },
        )
        return ClinicalContextService._report_read(report)

    @staticmethod
    @clinical_record_write
    def supersede_report(
        db: Session,
        report_id: str,
        payload: ParaclinicalReportSupersede,
        *,
        actor: User | None,
    ) -> ParaclinicalReportRead:
        actor = ClinicalContextService._require_actor(actor, AUTHOR_ROLES)
        previous = ClinicalContextService._require_report(
            db,
            report_id,
            for_update=True,
        )
        ClinicalContextService._verify_report(previous)
        if previous.status not in {"final", "entered_in_error"}:
            raise ClinicalContextConflictError(
                "Only a current final or entered-in-error paraclinical report "
                "can receive a replacement."
            )
        if ClinicalContextRepository.get_report_successor(db, previous.id) is not None:
            raise ClinicalContextConflictError(
                "A correction already exists for this paraclinical report."
            )
        content = ParaclinicalReportContent.model_validate(
            payload.model_dump(exclude={"revision_reason"})
        )
        version = previous.version + 1
        digest = paraclinical_report_digest(
            visit_id=previous.visit_id,
            report_key=previous.report_key,
            version=version,
            content=content,
            supersedes_report_id=previous.id,
            revision_reason=payload.revision_reason,
        )
        replacement = ClinicalContextRepository.create_report(
            db,
            visit_id=previous.visit_id,
            report_key=previous.report_key,
            version=version,
            content=content,
            content_sha256=digest,
            created_by_user_id=actor.id,
            supersedes_report_id=previous.id,
            revision_reason=payload.revision_reason,
        )
        ClinicalContextService._audit(
            db,
            entity_type="paraclinical_report",
            entity_id=replacement.id,
            event_type="paraclinical_report_correction_created",
            actor=actor,
            from_state=None,
            to_state="draft",
            message="Correcting paraclinical report version created as draft.",
            event_data={
                "visit_id": replacement.visit_id,
                "report_key": replacement.report_key,
                "version": replacement.version,
                "supersedes_report_id": previous.id,
                "observation_count": len(replacement.observations),
                "content_sha256": replacement.content_sha256,
            },
        )
        return ClinicalContextService._report_read(replacement)

    @staticmethod
    @clinical_record_write
    def enter_report_in_error(
        db: Session,
        report_id: str,
        payload: EnterClinicalRecordInError,
        *,
        actor: User | None,
    ) -> ParaclinicalReportRead:
        actor = ClinicalContextService._require_actor(actor, FINALIZE_ROLES)
        report = ClinicalContextService._require_report(
            db,
            report_id,
            for_update=True,
        )
        ClinicalContextService._verify_report(report)
        if report.status != "final":
            raise ClinicalContextConflictError(
                "Only a current final paraclinical report can be entered in error."
            )
        if ClinicalContextRepository.get_report_successor(db, report.id) is not None:
            raise ClinicalContextConflictError(
                "This paraclinical report already has a correction."
            )
        report.status = "entered_in_error"
        report.entered_in_error_by_user_id = actor.id
        report.entered_in_error_at = datetime.now(timezone.utc)
        report.error_reason = payload.reason
        ClinicalContextService._audit(
            db,
            entity_type="paraclinical_report",
            entity_id=report.id,
            event_type="paraclinical_report_entered_in_error",
            actor=actor,
            from_state="final",
            to_state="entered_in_error",
            message="Paraclinical report marked as entered in error.",
            event_data={
                "visit_id": report.visit_id,
                "report_key": report.report_key,
                "version": report.version,
                "content_sha256": report.content_sha256,
                "reason_recorded": True,
            },
        )
        return ClinicalContextService._report_read(report)

    @staticmethod
    def list_report_audit_logs(
        db: Session,
        report_id: str,
    ) -> list[AuditLog]:
        report = ClinicalContextService._require_report(db, report_id)
        ClinicalContextService._verify_report(report)
        return AuditLogRepository.list_by_entity(
            db,
            entity_type="paraclinical_report",
            entity_id=report_id,
        )

    @staticmethod
    def get_current_context(db: Session, visit_id: str) -> ClinicalContextRead:
        ClinicalContextService._require_visit(db, visit_id)
        intake = ClinicalContextRepository.get_current_final_intake(db, visit_id)
        reports = ClinicalContextRepository.list_current_final_reports(db, visit_id)
        return ClinicalContextRead(
            visit_id=visit_id,
            generated_at=datetime.now(timezone.utc),
            intake=(
                ClinicalContextService._intake_read(intake)
                if intake is not None
                else None
            ),
            reports=[
                ClinicalContextService._report_read(report)
                for report in reports
            ],
        )
