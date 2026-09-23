from copy import deepcopy

from sqlalchemy.orm import Session

from backend.app.db.clinical_record_transactions import clinical_record_write
from backend.app.models.treatment import Treatment
from backend.app.models.user import User
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.repositories.protocol import ProtocolRepository
from backend.app.repositories.treatment import TreatmentRepository
from backend.app.repositories.visit import VisitRepository
from backend.app.schemas.treatment import TreatmentCreate, TreatmentUpdate
from backend.app.services.audit_context import actor_data
from backend.app.services.clinical_context import (
    ClinicalContextIntegrityError,
    ClinicalContextNotFoundError,
    ClinicalContextService,
)
from backend.app.services.clinical_safety import clinical_context_digest
from backend.app.services.treatment_decision import (
    TreatmentDecisionConflictError,
    TreatmentDecisionIntegrityError,
    TreatmentDecisionNotFoundError,
    TreatmentDecisionService,
)
from backend.app.services.pilot_enrollment import (
    PilotEnrollmentConflictError,
    PilotEnrollmentIntegrityError,
    PilotVisitEnrollmentService,
)


class TreatmentNotFoundError(Exception):
    pass


class TreatmentVisitNotFoundError(Exception):
    pass


class TreatmentProtocolNotFoundError(Exception):
    pass


class TreatmentProtocolMismatchError(Exception):
    pass


class TreatmentProtocolInactiveError(Exception):
    pass


class TreatmentDecisionLinkError(Exception):
    pass


class TreatmentService:
    @staticmethod
    def _validate_decision_link(
        db: Session,
        visit_id: str,
        payload: TreatmentCreate,
        *,
        protocol,
    ) -> str | None:
        if payload.source_treatment_decision_id is None:
            return None
        if protocol is None:
            raise TreatmentDecisionLinkError(
                "A treatment linked to a clinician decision must use an "
                "active protocol template."
            )
        try:
            decision = TreatmentDecisionService.get(
                db,
                payload.source_treatment_decision_id,
            )
        except TreatmentDecisionNotFoundError as error:
            raise TreatmentDecisionLinkError(str(error)) from error
        except TreatmentDecisionIntegrityError as error:
            raise TreatmentDecisionLinkError(str(error)) from error

        if decision.visit_id != visit_id:
            raise TreatmentDecisionLinkError(
                "The clinician decision belongs to a different visit."
            )
        if not decision.is_current_decision:
            raise TreatmentDecisionLinkError(
                "The clinician decision has been superseded; reload the "
                "current decision before creating treatment."
            )
        if decision.decision_type in {"defer", "no_treatment"}:
            raise TreatmentDecisionLinkError(
                "The current clinician decision does not authorize creation "
                "of a treatment plan."
            )
        try:
            context = ClinicalContextService.get_current_context(
                db,
                visit_id,
            )
        except ClinicalContextNotFoundError as error:
            raise TreatmentDecisionLinkError(str(error)) from error
        except ClinicalContextIntegrityError as error:
            raise TreatmentDecisionLinkError(str(error)) from error
        if clinical_context_digest(context) != decision.clinical_context_sha256:
            raise TreatmentDecisionLinkError(
                "The clinical context changed after the clinician decision; "
                "record a new decision before creating treatment."
            )

        exact_reference = (
            protocol.code,
            protocol.version,
            protocol.treatment_type,
        )
        decision_references = {
            (
                item.protocol_code,
                item.protocol_version,
                item.treatment_type,
            )
            for item in decision.selected_protocols
        }
        if exact_reference not in decision_references:
            raise TreatmentDecisionLinkError(
                "The selected treatment protocol is not part of the current "
                "clinician decision."
            )
        return decision.sha256

    @staticmethod
    @clinical_record_write
    def create_treatment(
        db: Session,
        visit_id: str,
        payload: TreatmentCreate,
        actor: User | None = None,
    ) -> Treatment:
        visit = VisitRepository.get_by_id(db, visit_id)
        if visit is None:
            raise TreatmentVisitNotFoundError(
                f"Visit '{visit_id}' was not found."
            )

        protocol = None
        protocol_name = None
        protocol_version = None
        protocol_snapshot = None

        if payload.protocol_template_id is not None:
            protocol = ProtocolRepository.get_by_id(
                db,
                payload.protocol_template_id,
            )
            if protocol is None:
                raise TreatmentProtocolNotFoundError(
                    f"Protocol '{payload.protocol_template_id}' was not found."
                )
            if not protocol.is_active:
                raise TreatmentProtocolInactiveError(
                    f"Protocol '{protocol.id}' is inactive."
                )
            if protocol.treatment_type != payload.treatment_type:
                raise TreatmentProtocolMismatchError(
                    "Treatment type does not match protocol type. "
                    f"Treatment='{payload.treatment_type}', "
                    f"Protocol='{protocol.treatment_type}'."
                )
            protocol_name = protocol.name
            protocol_version = protocol.version
            protocol_snapshot = {
                "source_template_id": protocol.id,
                "code": protocol.code,
                "name": protocol.name,
                "treatment_type": protocol.treatment_type,
                "version": protocol.version,
                "description": protocol.description,
                "preparation_parameters": deepcopy(
                    protocol.preparation_parameters
                ),
                "administration_parameters": deepcopy(
                    protocol.administration_parameters
                ),
                "monitoring_parameters": deepcopy(
                    protocol.monitoring_parameters
                ),
            }

        PilotVisitEnrollmentService.validate_runtime_scope(
            db,
            visit_id,
            payload.protocol_template_id,
        )

        source_decision_sha256 = TreatmentService._validate_decision_link(
            db,
            visit_id,
            payload,
            protocol=protocol,
        )

        treatment = TreatmentRepository.create(
            db,
            visit_id,
            payload,
            protocol_name=protocol_name,
            protocol_version=protocol_version,
            protocol_snapshot=protocol_snapshot,
            source_treatment_decision_sha256=source_decision_sha256,
            commit=False,
        )
        AuditLogRepository.create(
            db,
            commit=False,
            entity_type="treatment",
            entity_id=treatment.id,
            event_type="treatment_created",
            from_state=None,
            to_state=treatment.status,
            message="Treatment plan created.",
            event_data={
                "visit_id": visit_id,
                "treatment_type": treatment.treatment_type,
                "protocol_template_id": treatment.protocol_template_id,
                "source_treatment_decision_id": (
                    treatment.source_treatment_decision_id
                ),
                "source_treatment_decision_sha256": (
                    treatment.source_treatment_decision_sha256
                ),
            },
            **actor_data(actor),
        )
        return treatment

    @staticmethod
    def get_treatment(
        db: Session,
        treatment_id: str,
    ) -> Treatment:
        treatment = TreatmentRepository.get_by_id(db, treatment_id)
        if treatment is None:
            raise TreatmentNotFoundError(
                f"Treatment '{treatment_id}' was not found."
            )
        return treatment

    @staticmethod
    def list_visit_treatments(
        db: Session,
        visit_id: str,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Treatment]:
        visit = VisitRepository.get_by_id(db, visit_id)
        if visit is None:
            raise TreatmentVisitNotFoundError(
                f"Visit '{visit_id}' was not found."
            )
        return TreatmentRepository.list_by_visit(
            db,
            visit_id,
            skip=skip,
            limit=limit,
        )

    @staticmethod
    def update_treatment(
        db: Session,
        treatment_id: str,
        payload: TreatmentUpdate,
        actor: User | None = None,
    ) -> Treatment:
        treatment = TreatmentService.get_treatment(db, treatment_id)
        old_status = treatment.status
        update_data = payload.model_dump(exclude_unset=True)
        changed_fields = list(update_data.keys())
        updated_treatment = TreatmentRepository.update(
            db,
            treatment,
            payload,
        )
        new_status = updated_treatment.status
        status_changed = old_status != new_status

        AuditLogRepository.create(
            db,
            entity_type="treatment",
            entity_id=updated_treatment.id,
            event_type="treatment_updated",
            from_state=(old_status if status_changed else None),
            to_state=(new_status if status_changed else None),
            message="Treatment plan updated.",
            event_data={
                "visit_id": updated_treatment.visit_id,
                "changed_fields": changed_fields,
            },
            **actor_data(actor),
        )
        return updated_treatment
