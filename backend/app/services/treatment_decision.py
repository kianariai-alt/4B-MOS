"""Append-only clinician decisions over an exact treatment-options roadmap."""
from copy import deepcopy
from datetime import datetime, timezone
import uuid

from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.app.db.clinical_record_transactions import clinical_record_write
from backend.app.models.audit_log import AuditLog
from backend.app.models.treatment_decision import TreatmentDecision
from backend.app.models.user import User
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.repositories.protocol import ProtocolRepository
from backend.app.repositories.treatment_decision import TreatmentDecisionRepository
from backend.app.repositories.visit import VisitRepository
from backend.app.schemas.treatment_decision import (
    DecisionProtocolReference,
    TreatmentDecisionCreate,
    TreatmentDecisionPayloadRead,
    TreatmentDecisionRead,
)
from backend.app.services.audit_context import actor_data
from backend.app.services.clinical_context import (
    ClinicalContextIntegrityError,
    ClinicalContextNotFoundError,
    ClinicalContextService,
)
from backend.app.services.clinical_evidence import (
    ClinicalEvidenceBriefService,
    ClinicalEvidenceIntegrityError,
)
from backend.app.services.clinical_safety import clinical_context_digest
from backend.app.services.session_finalization import evidence_digest


class TreatmentDecisionNotFoundError(Exception):
    pass


class TreatmentDecisionConflictError(Exception):
    pass


class TreatmentDecisionAuthorizationError(Exception):
    pass


class TreatmentDecisionIntegrityError(Exception):
    pass


def _same_timestamp(payload_value: str, column_value: datetime) -> bool:
    try:
        parsed = datetime.fromisoformat(payload_value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    if column_value.tzinfo is None:
        column_value = column_value.replace(tzinfo=timezone.utc)
    else:
        column_value = column_value.astimezone(timezone.utc)
    return parsed == column_value


class TreatmentDecisionService:
    @staticmethod
    def _require_actor(actor: User | None) -> User:
        if (
            actor is None
            or not actor.is_active
            or actor.role != "physician"
        ):
            raise TreatmentDecisionAuthorizationError(
                "Only an active physician may record a treatment decision."
            )
        return actor

    @staticmethod
    def _require_visit(db: Session, visit_id: str):
        visit = VisitRepository.get_by_id(db, visit_id)
        if visit is None:
            raise TreatmentDecisionNotFoundError(
                f"Visit '{visit_id}' was not found."
            )
        return visit

    @staticmethod
    def _evidence_hashes(
        db: Session,
        visit_id: str,
        evidence_brief_ids: list[str],
        *,
        clinical_context_sha256: str,
    ) -> list[str]:
        if not evidence_brief_ids:
            return []
        try:
            briefs = ClinicalEvidenceBriefService.list_for_visit(
                db,
                visit_id,
            )
        except ClinicalEvidenceIntegrityError as error:
            raise TreatmentDecisionIntegrityError(str(error)) from error
        by_id = {item.id: item for item in briefs}
        hashes: list[str] = []
        for brief_id in evidence_brief_ids:
            brief = by_id.get(brief_id)
            if brief is None:
                raise TreatmentDecisionConflictError(
                    f"Evidence brief '{brief_id}' does not belong to this visit."
                )
            if brief.clinical_context_sha256 != clinical_context_sha256:
                raise TreatmentDecisionConflictError(
                    "Only evidence briefs bound to the current clinical "
                    "context may be cited by a new treatment decision."
                )
            hashes.append(brief.sha256)
        return hashes

    @staticmethod
    def _validate_protocol_selection(
        db: Session,
        payload: TreatmentDecisionCreate,
        roadmap,
    ) -> None:
        selection_types = {
            "select_option",
            "modify_option",
            "combine_options",
        }
        if payload.decision_type in selection_types:
            if roadmap.roadmap_status != "options_available":
                raise TreatmentDecisionConflictError(
                    "Roadmap options are not currently available for selection."
                )
            available = {
                (
                    option.protocol_code,
                    option.protocol_version,
                    option.treatment_type,
                )
                for option in roadmap.options
            }
            for reference in payload.selected_protocols:
                key = (
                    reference.protocol_code,
                    reference.protocol_version,
                    reference.treatment_type,
                )
                if key not in available:
                    raise TreatmentDecisionConflictError(
                        "A selected roadmap protocol is no longer present in "
                        "the exact current roadmap."
                    )
            return

        if payload.decision_type == "choose_outside_roadmap":
            if roadmap.safety_evaluation_status != "current":
                raise TreatmentDecisionConflictError(
                    "A protocol outside the roadmap cannot be chosen until "
                    "the current safety workflow is complete."
                )
            reference = payload.selected_protocols[0]
            protocol = ProtocolRepository.get_by_code_version(
                db,
                reference.protocol_code,
                reference.protocol_version,
            )
            if protocol is None or not protocol.is_active:
                raise TreatmentDecisionConflictError(
                    "The outside-roadmap protocol code/version is not active."
                )
            if protocol.treatment_type != reference.treatment_type:
                raise TreatmentDecisionConflictError(
                    "The outside-roadmap treatment type does not match the "
                    "active protocol."
                )

    @staticmethod
    def _validate(
        db: Session,
        record: TreatmentDecision,
        *,
        current_decision_id: str | None = None,
    ) -> TreatmentDecisionPayloadRead:
        try:
            raw = deepcopy(record.payload)
            payload = TreatmentDecisionPayloadRead.model_validate(raw)
            valid = (
                isinstance(raw, dict)
                and evidence_digest(raw) == record.sha256
                and payload.id == record.id
                and payload.visit_id == record.visit_id
                and payload.supersedes_decision_id
                == record.supersedes_decision_id
                and payload.decision_type == record.decision_type
                and payload.clinical_context_sha256
                == record.clinical_context_sha256
                and payload.roadmap_sha256 == record.roadmap_sha256
                and isinstance(payload.roadmap_snapshot, dict)
                and payload.roadmap_snapshot.get("roadmap_sha256")
                == record.roadmap_sha256
                and payload.roadmap_snapshot.get("visit_id")
                == record.visit_id
                and payload.roadmap_snapshot.get("target_profile", {}).get(
                    "clinical_context_sha256"
                ) == record.clinical_context_sha256
                and [
                    item.model_dump(mode="json")
                    for item in payload.selected_protocols
                ] == list(record.selected_protocols)
                and payload.rationale == record.rationale
                and payload.modification_summary
                == record.modification_summary
                and payload.patient_preference_summary
                == record.patient_preference_summary
                and payload.evidence_brief_ids
                == list(record.evidence_brief_ids)
                and payload.decided_by_user_id
                == record.decided_by_user_id
                and _same_timestamp(payload.decided_at, record.decided_at)
            )
            if record.supersedes_decision_id is None:
                valid = valid and payload.supersedes_decision_sha256 is None
            else:
                previous = TreatmentDecisionRepository.get_by_id(
                    db,
                    record.supersedes_decision_id,
                )
                valid = (
                    valid
                    and previous is not None
                    and payload.supersedes_decision_sha256
                    == previous.sha256
                )
            try:
                current_briefs = ClinicalEvidenceBriefService.list_for_visit(
                    db,
                    record.visit_id,
                )
                by_id = {item.id: item for item in current_briefs}
                current_hashes = [
                    by_id[brief_id].sha256
                    for brief_id in payload.evidence_brief_ids
                    if brief_id in by_id
                ]
                valid = (
                    valid
                    and len(current_hashes) == len(payload.evidence_brief_ids)
                    and current_hashes == payload.evidence_brief_sha256s
                )
            except ClinicalEvidenceIntegrityError:
                valid = False
        except (
            AttributeError,
            KeyError,
            TypeError,
            ValueError,
            ValidationError,
        ):
            valid = False
            payload = None
        if not valid or payload is None:
            raise TreatmentDecisionIntegrityError(
                "Stored treatment decision failed its integrity check."
            )
        return payload

    @staticmethod
    def _to_read(
        db: Session,
        record: TreatmentDecision,
        *,
        current_decision_id: str | None = None,
    ) -> TreatmentDecisionRead:
        payload = TreatmentDecisionService._validate(
            db,
            record,
            current_decision_id=current_decision_id,
        )
        if current_decision_id is None:
            latest = TreatmentDecisionRepository.latest_by_visit(
                db,
                record.visit_id,
            )
            current_decision_id = latest.id if latest is not None else None
        return TreatmentDecisionRead(
            id=record.id,
            visit_id=record.visit_id,
            supersedes_decision_id=record.supersedes_decision_id,
            decision_type=record.decision_type,
            clinical_context_sha256=record.clinical_context_sha256,
            roadmap_sha256=record.roadmap_sha256,
            selected_protocols=payload.selected_protocols,
            rationale=record.rationale,
            modification_summary=record.modification_summary,
            patient_preference_summary=record.patient_preference_summary,
            evidence_brief_ids=list(record.evidence_brief_ids),
            decided_by_user_id=record.decided_by_user_id,
            sha256=record.sha256,
            decided_at=record.decided_at,
            payload=payload,
            is_current_decision=(record.id == current_decision_id),
            linked_treatment_ids=TreatmentDecisionRepository.linked_treatment_ids(
                db,
                record.id,
            ),
            linked_outcome_ids=TreatmentDecisionRepository.linked_outcome_ids(
                db,
                record.id,
            ),
        )

    @staticmethod
    @clinical_record_write
    def create(
        db: Session,
        visit_id: str,
        payload: TreatmentDecisionCreate,
        *,
        actor: User | None,
    ) -> TreatmentDecisionRead:
        actor = TreatmentDecisionService._require_actor(actor)
        TreatmentDecisionService._require_visit(db, visit_id)
        try:
            context = ClinicalContextService.get_current_context(db, visit_id)
        except ClinicalContextNotFoundError as error:
            raise TreatmentDecisionNotFoundError(str(error)) from error
        except ClinicalContextIntegrityError as error:
            raise TreatmentDecisionIntegrityError(str(error)) from error

        context_sha256 = clinical_context_digest(context)
        if payload.expected_clinical_context_sha256 != context_sha256:
            raise TreatmentDecisionConflictError(
                "The clinical context changed; reload the physician copilot "
                "before recording a decision."
            )

        from backend.app.services.treatment_options_roadmap import (
            TreatmentOptionsRoadmapService,
            TreatmentRoadmapConflictError,
            TreatmentRoadmapIntegrityError,
            TreatmentRoadmapNotFoundError,
        )

        try:
            roadmap = TreatmentOptionsRoadmapService.get_roadmap(
                db,
                visit_id,
            )
        except TreatmentRoadmapNotFoundError as error:
            raise TreatmentDecisionNotFoundError(str(error)) from error
        except TreatmentRoadmapConflictError as error:
            raise TreatmentDecisionConflictError(str(error)) from error
        except TreatmentRoadmapIntegrityError as error:
            raise TreatmentDecisionIntegrityError(str(error)) from error

        if payload.expected_roadmap_sha256 != roadmap.roadmap_sha256:
            raise TreatmentDecisionConflictError(
                "The treatment options roadmap changed; reload it before "
                "recording a clinician decision."
            )
        if roadmap.target_profile.clinical_context_sha256 != context_sha256:
            raise TreatmentDecisionConflictError(
                "The roadmap is not bound to the current clinical context."
            )

        TreatmentDecisionService._validate_protocol_selection(
            db,
            payload,
            roadmap,
        )

        previous = TreatmentDecisionRepository.latest_by_visit(
            db,
            visit_id,
        )
        if previous is None:
            if payload.expected_previous_decision_sha256 is not None:
                raise TreatmentDecisionConflictError(
                    "No previous clinician decision exists for this visit."
                )
        else:
            TreatmentDecisionService._validate(db, previous)
            if payload.expected_previous_decision_sha256 != previous.sha256:
                raise TreatmentDecisionConflictError(
                    "A newer clinician decision exists; reload the decision "
                    "history before recording another one."
                )

        evidence_hashes = TreatmentDecisionService._evidence_hashes(
            db,
            visit_id,
            payload.evidence_brief_ids,
            clinical_context_sha256=context_sha256,
        )

        decision_id = str(uuid.uuid4())
        decided_at = datetime.now(timezone.utc)
        stored_payload = TreatmentDecisionPayloadRead(
            schema_version=1,
            id=decision_id,
            visit_id=visit_id,
            supersedes_decision_id=(previous.id if previous else None),
            supersedes_decision_sha256=(previous.sha256 if previous else None),
            decision_type=payload.decision_type,
            clinical_context_sha256=context_sha256,
            roadmap_sha256=roadmap.roadmap_sha256,
            roadmap_snapshot=roadmap.model_dump(mode="json"),
            selected_protocols=payload.selected_protocols,
            rationale=payload.rationale,
            modification_summary=payload.modification_summary,
            patient_preference_summary=payload.patient_preference_summary,
            evidence_brief_ids=list(payload.evidence_brief_ids),
            evidence_brief_sha256s=evidence_hashes,
            decided_by_user_id=actor.id,
            decided_at=decided_at.isoformat(),
        ).model_dump(mode="json")
        sha256 = evidence_digest(stored_payload)

        record = TreatmentDecisionRepository.create(
            db,
            decision_id=decision_id,
            visit_id=visit_id,
            supersedes_decision_id=(previous.id if previous else None),
            decision_type=payload.decision_type,
            clinical_context_sha256=context_sha256,
            roadmap_sha256=roadmap.roadmap_sha256,
            selected_protocols=[
                item.model_dump(mode="json")
                for item in payload.selected_protocols
            ],
            rationale=payload.rationale,
            modification_summary=payload.modification_summary,
            patient_preference_summary=payload.patient_preference_summary,
            evidence_brief_ids=list(payload.evidence_brief_ids),
            decided_by_user_id=actor.id,
            payload=stored_payload,
            sha256=sha256,
            decided_at=decided_at,
        )
        AuditLogRepository.create(
            db,
            commit=False,
            entity_type="treatment_decision",
            entity_id=record.id,
            event_type="treatment_decision_recorded",
            from_state=(previous.decision_type if previous else None),
            to_state=record.decision_type,
            message=(
                "An immutable physician-authored treatment decision was "
                "recorded against an exact roadmap snapshot."
            ),
            event_data={
                "visit_id": visit_id,
                "decision_type": record.decision_type,
                "roadmap_sha256": roadmap.roadmap_sha256,
                "clinical_context_sha256": context_sha256,
                "decision_sha256": sha256,
                "selected_protocol_count": len(record.selected_protocols),
                "supersedes_decision_id": record.supersedes_decision_id,
                "is_system_selected": False,
            },
            **actor_data(actor),
        )
        return TreatmentDecisionService._to_read(
            db,
            record,
            current_decision_id=record.id,
        )

    @staticmethod
    def get(
        db: Session,
        decision_id: str,
    ) -> TreatmentDecisionRead:
        record = TreatmentDecisionRepository.get_by_id(db, decision_id)
        if record is None:
            raise TreatmentDecisionNotFoundError(
                f"Treatment decision '{decision_id}' was not found."
            )
        latest = TreatmentDecisionRepository.latest_by_visit(
            db,
            record.visit_id,
        )
        return TreatmentDecisionService._to_read(
            db,
            record,
            current_decision_id=(latest.id if latest else None),
        )

    @staticmethod
    def list_for_visit(
        db: Session,
        visit_id: str,
    ) -> list[TreatmentDecisionRead]:
        TreatmentDecisionService._require_visit(db, visit_id)
        records = TreatmentDecisionRepository.list_by_visit(db, visit_id)
        current_id = records[-1].id if records else None
        return [
            TreatmentDecisionService._to_read(
                db,
                record,
                current_decision_id=current_id,
            )
            for record in records
        ]

    @staticmethod
    def get_current_record(
        db: Session,
        visit_id: str,
    ) -> TreatmentDecision | None:
        record = TreatmentDecisionRepository.latest_by_visit(db, visit_id)
        if record is not None:
            TreatmentDecisionService._validate(db, record)
        return record

    @staticmethod
    def list_audit_logs(
        db: Session,
        decision_id: str,
    ) -> list[AuditLog]:
        TreatmentDecisionService.get(db, decision_id)
        return AuditLogRepository.list_by_entity(
            db,
            entity_type="treatment_decision",
            entity_id=decision_id,
        )
