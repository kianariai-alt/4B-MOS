from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PatientCreate(BaseModel):
    patient_code: str = Field(min_length=1, max_length=50)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    date_of_birth: date | None = None

    @field_validator("date_of_birth")
    @classmethod
    def validate_date_of_birth(cls, value: date | None) -> date | None:
        if value is not None and value > date.today():
            raise ValueError("date_of_birth cannot be in the future")

        return value


class PatientUpdate(BaseModel):
    first_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )

    last_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )

    date_of_birth: date | None = None
    is_active: bool | None = None

    @field_validator("date_of_birth")
    @classmethod
    def validate_date_of_birth(cls, value: date | None) -> date | None:
        if value is not None and value > date.today():
            raise ValueError("date_of_birth cannot be in the future")

        return value


class PatientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    patient_code: str
    first_name: str
    last_name: str
    date_of_birth: date | None
    is_active: bool
    created_at: datetime
    updated_at: datetime