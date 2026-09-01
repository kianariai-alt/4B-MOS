from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models.treatment_component import (
    TreatmentComponent,
)
from backend.app.models.user import User
from backend.app.repositories.audit_log import (
    AuditLogRepository,
)
from backend.app.repositories.orthobiologic_material import (
    OrthobiologicMaterialRepository,
)
from backend.app.repositories.treatment_component import (
    TreatmentComponentRepository,
)
from backend.app.schemas.treatment_component import (
    TreatmentComponentCreate,
    TreatmentComponentUpdate,
)
from backend.app.services.audit_context import (
    actor_data,
)
from backend.app.services.treatment import (
    TreatmentService,
)


class TreatmentComponentNotFoundError(
    Exception
):
    pass


class TreatmentComponentMaterialNotFoundError(
    Exception
):
    pass


class TreatmentComponentMaterialInactiveError(
    Exception
):
    pass


class TreatmentComponentDuplicateMaterialError(
    Exception
):
    pass


class TreatmentComponentSequenceConflictError(
    Exception
):
    pass


class TreatmentComponentLockedError(
    Exception
):
    pass


class TreatmentComponentReferencedError(
    Exception
):
    pass


def _decimal_text(
    value: Decimal | None,
) -> str | None:
    if value is None:
        return None

    return str(value)


class TreatmentComponentService:
    @staticmethod
    def _ensure_mutable(
        treatment,
    ) -> None:
        if treatment.status != "planned":
            raise TreatmentComponentLockedError(
                "Treatment combination can only "
                "be changed while the treatment "
                "status is 'planned'."
            )

    @staticmethod
    def _ensure_not_referenced(
        db: Session,
        component: TreatmentComponent,
    ) -> None:
        is_referenced = (
            TreatmentComponentRepository
            .has_session_component_references(
                db,
                component.id,
            )
        )

        if is_referenced:
            raise TreatmentComponentReferencedError(
                "Treatment component is "
                "referenced by an actual "
                "administration record and "
                "can no longer be changed "
                "or deleted."
            )

    @staticmethod
    def create_component(
        db: Session,
        treatment_id: str,
        payload: TreatmentComponentCreate,
        actor: User | None = None,
    ) -> TreatmentComponent:
        treatment = (
            TreatmentService.get_treatment(
                db,
                treatment_id,
            )
        )

        (
            TreatmentComponentService
            ._ensure_mutable(treatment)
        )

        material = (
            OrthobiologicMaterialRepository
            .get_by_id(
                db,
                payload.material_id,
            )
        )

        if material is None:
            raise (
                TreatmentComponentMaterialNotFoundError(
                    "Orthobiologic material "
                    f"'{payload.material_id}' "
                    "was not found."
                )
            )

        if not material.is_active:
            raise (
                TreatmentComponentMaterialInactiveError(
                    "Orthobiologic material "
                    f"'{material.code}' is inactive."
                )
            )

        existing_material = (
            TreatmentComponentRepository
            .get_by_treatment_material(
                db,
                treatment_id,
                material.id,
            )
        )

        if existing_material is not None:
            raise (
                TreatmentComponentDuplicateMaterialError(
                    f"Material '{material.code}' "
                    "already exists in this "
                    "treatment combination."
                )
            )

        sequence = payload.sequence

        if sequence is None:
            sequence = (
                TreatmentComponentRepository
                .next_sequence(
                    db,
                    treatment_id,
                )
            )

        existing_sequence = (
            TreatmentComponentRepository
            .get_by_treatment_sequence(
                db,
                treatment_id,
                sequence,
            )
        )

        if existing_sequence is not None:
            raise (
                TreatmentComponentSequenceConflictError(
                    f"Sequence '{sequence}' "
                    "is already used in this "
                    "treatment combination."
                )
            )

        unit = payload.unit

        if unit is None:
            unit = material.default_unit

        try:
            component = (
                TreatmentComponentRepository
                .create(
                    db,
                    treatment_id,
                    payload,
                    sequence=sequence,
                    unit=unit,
                )
            )

        except IntegrityError as exc:
            db.rollback()

            raise (
                TreatmentComponentDuplicateMaterialError(
                    "Treatment component "
                    "conflicts with an existing "
                    "combination component."
                )
            ) from exc

        AuditLogRepository.create(
            db,
            entity_type="treatment_component",
            entity_id=component.id,
            event_type=(
                "treatment_component_created"
            ),
            from_state=None,
            to_state="planned",
            message=(
                "Treatment combination "
                "component created."
            ),
            event_data={
                "treatment_id": treatment_id,
                "material_id": material.id,
                "material_code": material.code,
                "planned_amount": (
                    _decimal_text(
                        component.planned_amount
                    )
                ),
                "unit": component.unit,
                "sequence": component.sequence,
            },
            **actor_data(actor),
        )

        return component

    @staticmethod
    def list_components(
        db: Session,
        treatment_id: str,
    ) -> list[TreatmentComponent]:
        TreatmentService.get_treatment(
            db,
            treatment_id,
        )

        return (
            TreatmentComponentRepository
            .list_by_treatment(
                db,
                treatment_id,
            )
        )

    @staticmethod
    def get_component(
        db: Session,
        treatment_id: str,
        component_id: str,
    ) -> TreatmentComponent:
        TreatmentService.get_treatment(
            db,
            treatment_id,
        )

        component = (
            TreatmentComponentRepository
            .get_by_id(
                db,
                component_id,
            )
        )

        if (
            component is None
            or component.treatment_id
            != treatment_id
        ):
            raise (
                TreatmentComponentNotFoundError(
                    "Treatment component "
                    f"'{component_id}' "
                    "was not found."
                )
            )

        return component

    @staticmethod
    def update_component(
        db: Session,
        treatment_id: str,
        component_id: str,
        payload: TreatmentComponentUpdate,
        actor: User | None = None,
    ) -> TreatmentComponent:
        treatment = (
            TreatmentService.get_treatment(
                db,
                treatment_id,
            )
        )

        (
            TreatmentComponentService
            ._ensure_mutable(treatment)
        )

        component = (
            TreatmentComponentService
            .get_component(
                db,
                treatment_id,
                component_id,
            )
        )

        update_data = payload.model_dump(
            exclude_unset=True,
        )

        if not update_data:
            return component

        (
            TreatmentComponentService
            ._ensure_not_referenced(
                db,
                component,
            )
        )

        if "sequence" in update_data:
            requested_sequence = (
                update_data["sequence"]
            )

            if (
                requested_sequence
                != component.sequence
            ):
                existing_sequence = (
                    TreatmentComponentRepository
                    .get_by_treatment_sequence(
                        db,
                        treatment_id,
                        requested_sequence,
                    )
                )

                if existing_sequence is not None:
                    raise (
                        TreatmentComponentSequenceConflictError(
                            f"Sequence "
                            f"'{requested_sequence}' "
                            "is already used in this "
                            "treatment combination."
                        )
                    )

        old_snapshot = {
            "planned_amount": _decimal_text(
                component.planned_amount
            ),
            "unit": component.unit,
            "sequence": component.sequence,
            "notes": component.notes,
        }

        try:
            updated_component = (
                TreatmentComponentRepository
                .update(
                    db,
                    component,
                    payload,
                )
            )

        except IntegrityError as exc:
            db.rollback()

            raise (
                TreatmentComponentSequenceConflictError(
                    "Treatment component "
                    "update conflicts with an "
                    "existing combination "
                    "component."
                )
            ) from exc

        new_snapshot = {
            "planned_amount": _decimal_text(
                updated_component.planned_amount
            ),
            "unit": updated_component.unit,
            "sequence": (
                updated_component.sequence
            ),
            "notes": updated_component.notes,
        }

        AuditLogRepository.create(
            db,
            entity_type="treatment_component",
            entity_id=updated_component.id,
            event_type=(
                "treatment_component_updated"
            ),
            from_state="planned",
            to_state="planned",
            message=(
                "Treatment combination "
                "component updated."
            ),
            event_data={
                "treatment_id": treatment_id,
                "material_id": (
                    updated_component.material_id
                ),
                "changed_fields": list(
                    update_data.keys()
                ),
                "before": old_snapshot,
                "after": new_snapshot,
            },
            **actor_data(actor),
        )

        return updated_component

    @staticmethod
    def delete_component(
        db: Session,
        treatment_id: str,
        component_id: str,
        actor: User | None = None,
    ) -> None:
        treatment = (
            TreatmentService.get_treatment(
                db,
                treatment_id,
            )
        )

        (
            TreatmentComponentService
            ._ensure_mutable(treatment)
        )

        component = (
            TreatmentComponentService
            .get_component(
                db,
                treatment_id,
                component_id,
            )
        )

        (
            TreatmentComponentService
            ._ensure_not_referenced(
                db,
                component,
            )
        )

        component_snapshot = {
            "treatment_id": treatment_id,
            "material_id": (
                component.material_id
            ),
            "planned_amount": (
                _decimal_text(
                    component.planned_amount
                )
            ),
            "unit": component.unit,
            "sequence": component.sequence,
            "notes": component.notes,
        }

        try:
            (
                TreatmentComponentRepository
                .delete(
                    db,
                    component,
                )
            )

        except IntegrityError as exc:
            db.rollback()

            raise TreatmentComponentReferencedError(
                "Treatment component is "
                "referenced by an actual "
                "administration record and "
                "cannot be deleted."
            ) from exc

        AuditLogRepository.create(
            db,
            entity_type="treatment_component",
            entity_id=component_id,
            event_type=(
                "treatment_component_deleted"
            ),
            from_state="planned",
            to_state=None,
            message=(
                "Treatment combination "
                "component deleted."
            ),
            event_data=component_snapshot,
            **actor_data(actor),
        )
