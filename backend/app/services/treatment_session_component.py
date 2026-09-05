from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from backend.app.db.transactions import atomic_write

from backend.app.models.treatment_session_component import (
    TreatmentSessionComponent,
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
from backend.app.repositories.treatment_session_component import (
    TreatmentSessionComponentRepository,
)
from backend.app.schemas.treatment_session_component import (
    TreatmentSessionComponentCreate,
    TreatmentSessionComponentUpdate,
)
from backend.app.services.audit_context import (
    actor_data,
)
from backend.app.services.treatment_session import (
    TreatmentSessionService,
)


class TreatmentSessionComponentNotFoundError(
    Exception
):
    pass


class TreatmentSessionComponentMaterialNotFoundError(
    Exception
):
    pass


class TreatmentSessionComponentMaterialInactiveError(
    Exception
):
    pass


class TreatmentSessionComponentPlanNotFoundError(
    Exception
):
    pass


class TreatmentSessionComponentPlanMismatchError(
    Exception
):
    pass


class TreatmentSessionComponentSequenceConflictError(
    Exception
):
    pass


class TreatmentSessionComponentLockedError(
    Exception
):
    pass


class TreatmentSessionComponentTraceabilityError(
    Exception
):
    pass


def _decimal_text(
    value: Decimal | None,
) -> str | None:
    if value is None:
        return None

    return str(value)


def _snapshot(
    component: TreatmentSessionComponent,
) -> dict:
    return {
        "treatment_session_id": (
            component.treatment_session_id
        ),
        "treatment_component_id": (
            component.treatment_component_id
        ),
        "material_id": (
            component.material_id
        ),
        "actual_amount": (
            _decimal_text(
                component.actual_amount
            )
        ),
        "unit": component.unit,
        "sequence": component.sequence,
        "source": component.source,
        "manufacturer": (
            component.manufacturer
        ),
        "product_name": (
            component.product_name
        ),
        "lot_number": (
            component.lot_number
        ),
        "batch_number": (
            component.batch_number
        ),
        "expiry_date": (
            component.expiry_date.isoformat()
            if component.expiry_date
            is not None
            else None
        ),
        "concentration": (
            component.concentration
        ),
        "preparation_method": (
            component.preparation_method
        ),
        "activation_method": (
            component.activation_method
        ),
        "storage_condition": (
            component.storage_condition
        ),
        "preparation_parameters": (
            component.preparation_parameters
        ),
        "notes": component.notes,
    }


class TreatmentSessionComponentService:
    @staticmethod
    def _ensure_mutable(
        treatment_session,
    ) -> None:
        if (
            treatment_session.status
            != "in_progress"
            or treatment_session.operational_status
            != "in_treatment"
        ):
            raise (
                TreatmentSessionComponentLockedError(
                    "Actual administration records "
                    "can only be changed while the "
                    "session is actively in "
                    "treatment."
                )
            )

    @staticmethod
    def _validate_traceability(
        *,
        requires_lot_tracking: bool,
        lot_number: str | None,
        batch_number: str | None,
    ) -> None:
        if (
            requires_lot_tracking
            and not lot_number
            and not batch_number
        ):
            raise (
                TreatmentSessionComponentTraceabilityError(
                    "This material requires lot "
                    "tracking. Provide lot_number "
                    "or batch_number."
                )
            )

    @staticmethod
    @atomic_write
    def create_component(
        db: Session,
        session_id: str,
        payload: TreatmentSessionComponentCreate,
        actor: User | None = None,
    ) -> TreatmentSessionComponent:
        treatment_session = (
            TreatmentSessionService.get_session(
                db,
                session_id,
            )
        )

        (
            TreatmentSessionComponentService
            ._ensure_mutable(
                treatment_session
            )
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
                TreatmentSessionComponentMaterialNotFoundError(
                    "Orthobiologic material "
                    f"'{payload.material_id}' "
                    "was not found."
                )
            )

        if not material.is_active:
            raise (
                TreatmentSessionComponentMaterialInactiveError(
                    "Orthobiologic material "
                    f"'{material.code}' is inactive."
                )
            )

        planned_component = None

        if (
            payload.treatment_component_id
            is not None
        ):
            planned_component = (
                TreatmentComponentRepository
                .get_by_id(
                    db,
                    payload.treatment_component_id,
                )
            )

            if planned_component is None:
                raise (
                    TreatmentSessionComponentPlanNotFoundError(
                        "Planned treatment "
                        "component "
                        f"'{payload.treatment_component_id}' "
                        "was not found."
                    )
                )

            if (
                planned_component.treatment_id
                != treatment_session.treatment_id
            ):
                raise (
                    TreatmentSessionComponentPlanMismatchError(
                        "Planned component does "
                        "not belong to the "
                        "treatment associated "
                        "with this session."
                    )
                )

            if (
                planned_component.material_id
                != material.id
            ):
                raise (
                    TreatmentSessionComponentPlanMismatchError(
                        "Material does not match "
                        "the linked planned "
                        "treatment component."
                    )
                )

        (
            TreatmentSessionComponentService
            ._validate_traceability(
                requires_lot_tracking=(
                    material.requires_lot_tracking
                ),
                lot_number=payload.lot_number,
                batch_number=payload.batch_number,
            )
        )

        sequence = payload.sequence

        if sequence is None:
            sequence = (
                TreatmentSessionComponentRepository
                .next_sequence(
                    db,
                    session_id,
                )
            )

        existing_sequence = (
            TreatmentSessionComponentRepository
            .get_by_session_sequence(
                db,
                session_id,
                sequence,
            )
        )

        if existing_sequence is not None:
            raise (
                TreatmentSessionComponentSequenceConflictError(
                    f"Sequence '{sequence}' "
                    "is already used in this "
                    "treatment session."
                )
            )

        unit = payload.unit

        if unit is None:
            unit = material.default_unit

        try:
            component = (
                TreatmentSessionComponentRepository
                .create(
                    db,
                    session_id,
                    payload,
                    sequence=sequence,
                    unit=unit,
                )
            )

        except IntegrityError as exc:
            db.rollback()

            raise (
                TreatmentSessionComponentSequenceConflictError(
                    "Session component "
                    "conflicts with an existing "
                    "administration record."
                )
            ) from exc

        AuditLogRepository.create(
            db,
            commit=False,
            entity_type=(
                "treatment_session_component"
            ),
            entity_id=component.id,
            event_type=(
                "session_component_created"
            ),
            from_state=None,
            to_state="recorded",
            message=(
                "Treatment session "
                "administration component "
                "recorded."
            ),
            event_data={
                **_snapshot(component),
                "material_code": material.code,
            },
            **actor_data(actor),
        )

        return component

    @staticmethod
    def list_components(
        db: Session,
        session_id: str,
    ) -> list[TreatmentSessionComponent]:
        TreatmentSessionService.get_session(
            db,
            session_id,
        )

        return (
            TreatmentSessionComponentRepository
            .list_by_session(
                db,
                session_id,
            )
        )

    @staticmethod
    def get_component(
        db: Session,
        session_id: str,
        component_id: str,
    ) -> TreatmentSessionComponent:
        TreatmentSessionService.get_session(
            db,
            session_id,
        )

        component = (
            TreatmentSessionComponentRepository
            .get_by_id(
                db,
                component_id,
            )
        )

        if (
            component is None
            or component.treatment_session_id
            != session_id
        ):
            raise (
                TreatmentSessionComponentNotFoundError(
                    "Treatment session "
                    "component "
                    f"'{component_id}' "
                    "was not found."
                )
            )

        return component

    @staticmethod
    @atomic_write
    def update_component(
        db: Session,
        session_id: str,
        component_id: str,
        payload: TreatmentSessionComponentUpdate,
        actor: User | None = None,
    ) -> TreatmentSessionComponent:
        treatment_session = (
            TreatmentSessionService.get_session(
                db,
                session_id,
            )
        )

        (
            TreatmentSessionComponentService
            ._ensure_mutable(
                treatment_session
            )
        )

        component = (
            TreatmentSessionComponentService
            .get_component(
                db,
                session_id,
                component_id,
            )
        )

        update_data = payload.model_dump(
            exclude_unset=True,
        )

        if not update_data:
            return component

        if "sequence" in update_data:
            requested_sequence = (
                update_data["sequence"]
            )

            if (
                requested_sequence
                != component.sequence
            ):
                existing = (
                    TreatmentSessionComponentRepository
                    .get_by_session_sequence(
                        db,
                        session_id,
                        requested_sequence,
                    )
                )

                if existing is not None:
                    raise (
                        TreatmentSessionComponentSequenceConflictError(
                            f"Sequence "
                            f"'{requested_sequence}' "
                            "is already used in "
                            "this treatment session."
                        )
                    )

        material = (
            OrthobiologicMaterialRepository
            .get_by_id(
                db,
                component.material_id,
            )
        )

        if material is None:
            raise (
                TreatmentSessionComponentMaterialNotFoundError(
                    "Linked orthobiologic "
                    "material was not found."
                )
            )

        prospective_lot = (
            update_data.get(
                "lot_number",
                component.lot_number,
            )
        )

        prospective_batch = (
            update_data.get(
                "batch_number",
                component.batch_number,
            )
        )

        (
            TreatmentSessionComponentService
            ._validate_traceability(
                requires_lot_tracking=(
                    material.requires_lot_tracking
                ),
                lot_number=prospective_lot,
                batch_number=prospective_batch,
            )
        )

        before = _snapshot(component)

        try:
            updated_component = (
                TreatmentSessionComponentRepository
                .update(
                    db,
                    component,
                    payload,
                )
            )

        except IntegrityError as exc:
            db.rollback()

            raise (
                TreatmentSessionComponentSequenceConflictError(
                    "Session component "
                    "update conflicts with an "
                    "existing administration "
                    "record."
                )
            ) from exc

        after = _snapshot(
            updated_component
        )

        AuditLogRepository.create(
            db,
            commit=False,
            entity_type=(
                "treatment_session_component"
            ),
            entity_id=updated_component.id,
            event_type=(
                "session_component_updated"
            ),
            from_state="recorded",
            to_state="recorded",
            message=(
                "Treatment session "
                "administration component "
                "updated."
            ),
            event_data={
                "changed_fields": list(
                    update_data.keys()
                ),
                "before": before,
                "after": after,
            },
            **actor_data(actor),
        )

        return updated_component

    @staticmethod
    @atomic_write
    def delete_component(
        db: Session,
        session_id: str,
        component_id: str,
        actor: User | None = None,
    ) -> None:
        treatment_session = (
            TreatmentSessionService.get_session(
                db,
                session_id,
            )
        )

        (
            TreatmentSessionComponentService
            ._ensure_mutable(
                treatment_session
            )
        )

        component = (
            TreatmentSessionComponentService
            .get_component(
                db,
                session_id,
                component_id,
            )
        )

        snapshot = _snapshot(
            component
        )

        (
            TreatmentSessionComponentRepository
            .delete(
                db,
                component,
            )
        )

        AuditLogRepository.create(
            db,
            commit=False,
            entity_type=(
                "treatment_session_component"
            ),
            entity_id=component_id,
            event_type=(
                "session_component_deleted"
            ),
            from_state="recorded",
            to_state=None,
            message=(
                "Treatment session "
                "administration component "
                "deleted."
            ),
            event_data=snapshot,
            **actor_data(actor),
        )
