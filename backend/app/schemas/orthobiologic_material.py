from datetime import datetime

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)


class OrthobiologicMaterialCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )

    code: str = Field(
        min_length=1,
        max_length=50,
    )

    name: str = Field(
        min_length=1,
        max_length=150,
    )

    category: str = Field(
        default="orthobiologic",
        min_length=1,
        max_length=50,
    )

    default_unit: str | None = Field(
        default=None,
        max_length=30,
    )

    description: str | None = None

    is_autologous: bool = False
    requires_lot_tracking: bool = False

    @field_validator("code")
    @classmethod
    def normalize_code(
        cls,
        value: str,
    ) -> str:
        normalized = value.strip().upper()

        if not normalized:
            raise ValueError(
                "Material code must not be blank."
            )

        return normalized

    @field_validator("name")
    @classmethod
    def normalize_name(
        cls,
        value: str,
    ) -> str:
        normalized = value.strip()

        if not normalized:
            raise ValueError(
                "Material name must not be blank."
            )

        return normalized

    @field_validator("category")
    @classmethod
    def normalize_category(
        cls,
        value: str,
    ) -> str:
        normalized = value.strip().lower()

        if not normalized:
            raise ValueError(
                "Material category must not be blank."
            )

        return normalized

    @field_validator("default_unit")
    @classmethod
    def normalize_default_unit(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        normalized = value.strip().lower()

        if not normalized:
            return None

        return normalized


class OrthobiologicMaterialRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
    )

    id: str
    code: str
    name: str
    category: str
    default_unit: str | None
    description: str | None

    is_autologous: bool
    requires_lot_tracking: bool
    is_active: bool

    created_at: datetime
    updated_at: datetime
