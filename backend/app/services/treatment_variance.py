from decimal import Decimal

from sqlalchemy.orm import Session

from backend.app.repositories.treatment_component import (
    TreatmentComponentRepository,
)
from backend.app.repositories.treatment_session_component import (
    TreatmentSessionComponentRepository,
)
from backend.app.schemas.treatment_variance import (
    PlannedComponentVarianceRead,
    TreatmentSessionVarianceRead,
    UnplannedAdministrationRead,
)
from backend.app.services.treatment_session import (
    TreatmentSessionService,
)


class TreatmentVarianceIntegrityError(
    Exception
):
    pass


class TreatmentVarianceService:
    @staticmethod
    def get_session_variance(
        db: Session,
        session_id: str,
    ) -> TreatmentSessionVarianceRead:
        treatment_session = (
            TreatmentSessionService.get_session(
                db,
                session_id,
            )
        )

        planned_components = (
            TreatmentComponentRepository
            .list_by_treatment(
                db,
                treatment_session.treatment_id,
            )
        )

        actual_components = (
            TreatmentSessionComponentRepository
            .list_by_session(
                db,
                session_id,
            )
        )

        planned_ids = {
            component.id
            for component
            in planned_components
        }

        actual_by_plan: dict[
            str,
            list,
        ] = {}

        unplanned_actual = []

        for actual in actual_components:
            planned_id = (
                actual.treatment_component_id
            )

            if planned_id is None:
                unplanned_actual.append(
                    actual
                )
                continue

            if planned_id not in planned_ids:
                raise (
                    TreatmentVarianceIntegrityError(
                        "Session administration "
                        "contains a planned "
                        "component link that does "
                        "not belong to the "
                        "session treatment."
                    )
                )

            actual_by_plan.setdefault(
                planned_id,
                [],
            ).append(actual)

        component_results = []

        counts = {
            "matched": 0,
            "under_administered": 0,
            "over_administered": 0,
            "omitted": 0,
            "unit_mismatch": 0,
            "unquantified": 0,
        }

        for planned in planned_components:
            linked = actual_by_plan.get(
                planned.id,
                [],
            )

            administration_count = len(
                linked
            )

            actual_amount = None
            actual_unit = None
            difference = None

            if not linked:
                variance_status = "omitted"

            else:
                actual_units = {
                    item.unit
                    for item in linked
                }

                all_amounts_known = all(
                    item.actual_amount
                    is not None
                    for item in linked
                )

                if all_amounts_known:
                    actual_amount = sum(
                        (
                            item.actual_amount
                            for item in linked
                        ),
                        Decimal("0"),
                    )

                if len(actual_units) == 1:
                    actual_unit = next(
                        iter(actual_units)
                    )

                if len(actual_units) != 1:
                    variance_status = (
                        "unit_mismatch"
                    )

                elif (
                    planned.unit is not None
                    and actual_unit is not None
                    and planned.unit
                    != actual_unit
                ):
                    variance_status = (
                        "unit_mismatch"
                    )

                elif (
                    planned.planned_amount
                    is None
                    or actual_amount is None
                    or planned.unit is None
                    or actual_unit is None
                ):
                    variance_status = (
                        "unquantified"
                    )

                else:
                    difference = (
                        actual_amount
                        - planned.planned_amount
                    )

                    if difference == 0:
                        variance_status = (
                            "matched"
                        )

                    elif difference < 0:
                        variance_status = (
                            "under_administered"
                        )

                    else:
                        variance_status = (
                            "over_administered"
                        )

            counts[
                variance_status
            ] += 1

            component_results.append(
                PlannedComponentVarianceRead(
                    treatment_component_id=(
                        planned.id
                    ),
                    material_id=(
                        planned.material_id
                    ),
                    material_code=(
                        planned.material.code
                    ),
                    material_name=(
                        planned.material.name
                    ),
                    planned_amount=(
                        planned.planned_amount
                    ),
                    planned_unit=planned.unit,
                    actual_amount=actual_amount,
                    actual_unit=actual_unit,
                    difference=difference,
                    status=variance_status,
                    administration_count=(
                        administration_count
                    ),
                )
            )

        unplanned_results = [
            UnplannedAdministrationRead(
                session_component_id=(
                    item.id
                ),
                material_id=(
                    item.material_id
                ),
                material_code=(
                    item.material.code
                ),
                material_name=(
                    item.material.name
                ),
                actual_amount=(
                    item.actual_amount
                ),
                unit=item.unit,
                sequence=item.sequence,
                lot_number=item.lot_number,
                batch_number=(
                    item.batch_number
                ),
            )
            for item in unplanned_actual
        ]

        linked_administration_count = sum(
            1
            for item in actual_components
            if (
                item.treatment_component_id
                is not None
            )
        )

        return TreatmentSessionVarianceRead(
            session_id=treatment_session.id,
            treatment_id=(
                treatment_session.treatment_id
            ),
            planned_count=len(
                planned_components
            ),
            linked_administration_count=(
                linked_administration_count
            ),
            unplanned_count=len(
                unplanned_results
            ),
            matched_count=counts[
                "matched"
            ],
            under_administered_count=counts[
                "under_administered"
            ],
            over_administered_count=counts[
                "over_administered"
            ],
            omitted_count=counts[
                "omitted"
            ],
            unit_mismatch_count=counts[
                "unit_mismatch"
            ],
            unquantified_count=counts[
                "unquantified"
            ],
            components=component_results,
            unplanned_administrations=(
                unplanned_results
            ),
        )
