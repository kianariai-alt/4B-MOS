from datetime import (
    date,
    datetime,
)
from decimal import Decimal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from backend.app.schemas.treatment_component import (
    TreatmentComponentMaterialRead,
)


class TreatmentSessionComponentCreate(
    BaseModel
):
    model_config = ConfigDict(
        extra="forbid",
    )

    treatment_component_id: str | None = Field(
        default=None,
        max_length=36,
    )

    material_id: str = Field(
        min_length=1,
        max_length=36,
    )

    actual_amount: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=12,
        decimal_places=4,
    )

    unit: str | None = Field(
        default=None,
        max_length=30,
    )

    sequence: int | None = Field(
        default=None,
        ge=1,
    )

    source: str | None = Field(
        default=None,
        max_length=100,
    )

    manufacturer: str | None = Field(
        default=None,
        max_length=200,
    )

    product_name: str | None = Field(
        default=None,
        max_length=200,
    )

    lot_number: str | None = Field(
        default=None,
        max_length=100,
    )

    batch_number: str | None = Field(
        default=None,
        max_length=100,
    )

    expiry_date: date | None = None

    concentration: str | None = Field(
        default=None,
        max_length=100,
    )

    preparation_method: str | None = Field(
        default=None,
        max_length=5000,
    )

    activation_method: str | None = Field(
        default=None,
        max_length=5000,
    )

    storage_condition: str | None = Field(
        default=None,
        max_length=200,
    )

    preparation_parameters: dict | None = None

    notes: str | None = Field(
        default=None,
        max_length=5000,
    )

    @field_validator("material_id")
    @classmethod
    def normalize_material_id(
        cls,
        value: str,
    ) -> str:
        normalized = value.strip()

        if not normalized:
            raise ValueError(
                "material_id must not be blank."
            )

        return normalized

    @field_validator("treatment_component_id")
    @classmethod
    def normalize_treatment_component_id(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        normalized = value.strip()

        return normalized or None

    @field_validator("unit")
    @classmethod
    def normalize_unit(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        normalized = value.strip().lower()

        return normalized or None

    @field_validator(
        "source",
        "manufacturer",
        "product_name",
        "lot_number",
        "batch_number",
        "concentration",
        "preparation_method",
        "activation_method",
        "storage_condition",
        "notes",
    )
    @classmethod
    def normalize_optional_text(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        normalized = value.strip()

        return normalized or None


class TreatmentSessionComponentUpdate(
    BaseModel
):
    model_config = ConfigDict(
        extra="forbid",
    )

    actual_amount: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=12,
        decimal_places=4,
    )

    unit: str | None = Field(
        default=None,
        max_length=30,
    )

    sequence: int | None = Field(
        default=None,
        ge=1,
    )

    source: str | None = Field(
        default=None,
        max_length=100,
    )

    manufacturer: str | None = Field(
        default=None,
        max_length=200,
    )

    product_name: str | None = Field(
        default=None,
        max_length=200,
    )

    lot_number: str | None = Field(
        default=None,
        max_length=100,
    )

    batch_number: str | None = Field(
        default=None,
        max_length=100,
    )

    expiry_date: date | None = None

    concentration: str | None = Field(
        default=None,
        max_length=100,
    )

    preparation_method: str | None = Field(
        default=None,
        max_length=5000,
    )

    activation_method: str | None = Field(
        default=None,
        max_length=5000,
    )

    storage_condition: str | None = Field(
        default=None,
        max_length=200,
    )

    preparation_parameters: dict | None = None

    notes: str | None = Field(
        default=None,
        max_length=5000,
    )

    @field_validator("unit")
    @classmethod
    def normalize_unit(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        normalized = value.strip().lower()

        return normalized or None

    @field_validator(
        "source",
        "manufacturer",
        "product_name",
        "lot_number",
        "batch_number",
        "concentration",
        "preparation_method",
        "activation_method",
        "storage_condition",
        "notes",
    )
    @classmethod
    def normalize_optional_text(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        normalized = value.strip()

        return normalized or None

    @model_validator(mode="after")
    def validate_sequence_not_null(
        self,
    ):
        if (
            "sequence" in self.model_fields_set
            and self.sequence is None
        ):
            raise ValueError(
                "sequence cannot be null."
            )

        return self


class TreatmentSessionComponentRead(
    BaseModel
):
    model_config = ConfigDict(
        from_attributes=True,
    )

    id: str
    treatment_session_id: str
    treatment_component_id: str | None
    material_id: str

    actual_amount: Decimal | None
    unit: str | None
    sequence: int

    source: str | None

    manufacturer: str | None
    product_name: str | None
    lot_number: str | None
    batch_number: str | None
    expiry_date: date | None
    concentration: str | None

    preparation_method: str | None
    activation_method: str | None
    storage_condition: str | None
    preparation_parameters: dict | None

    notes: str | None

    material: TreatmentComponentMaterialRead

    created_at: datetime
    updated_at: datetime
