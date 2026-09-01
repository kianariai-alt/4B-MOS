from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


TreatmentVarianceStatus = Literal[
    "matched",
    "under_administered",
    "over_administered",
    "omitted",
    "unit_mismatch",
    "unquantified",
]


class PlannedComponentVarianceRead(
    BaseModel
):
    treatment_component_id: str

    material_id: str
    material_code: str
    material_name: str

    planned_amount: Decimal | None
    planned_unit: str | None

    actual_amount: Decimal | None
    actual_unit: str | None

    difference: Decimal | None

    status: TreatmentVarianceStatus

    administration_count: int


class UnplannedAdministrationRead(
    BaseModel
):
    session_component_id: str

    material_id: str
    material_code: str
    material_name: str

    actual_amount: Decimal | None
    unit: str | None
    sequence: int

    lot_number: str | None
    batch_number: str | None


class TreatmentSessionVarianceRead(
    BaseModel
):
    session_id: str
    treatment_id: str

    planned_count: int
    linked_administration_count: int
    unplanned_count: int

    matched_count: int
    under_administered_count: int
    over_administered_count: int
    omitted_count: int
    unit_mismatch_count: int
    unquantified_count: int

    components: list[
        PlannedComponentVarianceRead
    ]

    unplanned_administrations: list[
        UnplannedAdministrationRead
    ]
