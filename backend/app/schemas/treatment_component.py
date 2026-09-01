from datetime import datetime
from decimal import Decimal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class TreatmentComponentCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )

    material_id: str = Field(
        min_length=1,
        max_length=36,
    )

    planned_amount: Decimal | None = Field(
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


class TreatmentComponentUpdate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )

    planned_amount: Decimal | None = Field(
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


class TreatmentComponentMaterialRead(
    BaseModel
):
    model_config = ConfigDict(
        from_attributes=True,
    )

    id: str
    code: str
    name: str
    category: str
    default_unit: str | None
    is_active: bool


class TreatmentComponentRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
    )

    id: str
    treatment_id: str
    material_id: str

    planned_amount: Decimal | None
    unit: str | None
    sequence: int
    notes: str | None

    material: TreatmentComponentMaterialRead

    created_at: datetime
    updated_at: datetime
