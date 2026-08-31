from copy import deepcopy

from sqlalchemy.orm import Session

from backend.app.models.treatment import Treatment
from backend.app.repositories.protocol import ProtocolRepository
from backend.app.repositories.treatment import TreatmentRepository
from backend.app.repositories.visit import VisitRepository
from backend.app.schemas.treatment import (
    TreatmentCreate,
    TreatmentUpdate,
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


class TreatmentService:
    @staticmethod
    def create_treatment(
        db: Session,
        visit_id: str,
        payload: TreatmentCreate,
    ) -> Treatment:
        visit = VisitRepository.get_by_id(
            db,
            visit_id,
        )

        if visit is None:
            raise TreatmentVisitNotFoundError(
                f"Visit '{visit_id}' was not found."
            )

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
                    f"Protocol '{payload.protocol_template_id}' "
                    "was not found."
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

        return TreatmentRepository.create(
            db,
            visit_id,
            payload,
            protocol_name=protocol_name,
            protocol_version=protocol_version,
            protocol_snapshot=protocol_snapshot,
        )

    @staticmethod
    def get_treatment(
        db: Session,
        treatment_id: str,
    ) -> Treatment:
        treatment = TreatmentRepository.get_by_id(
            db,
            treatment_id,
        )

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
        visit = VisitRepository.get_by_id(
            db,
            visit_id,
        )

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
    ) -> Treatment:
        treatment = TreatmentService.get_treatment(
            db,
            treatment_id,
        )

        return TreatmentRepository.update(
            db,
            treatment,
            payload,
        )