from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)


UserRole = Literal[
    "admin",
    "physician",
    "nurse",
    "operator",
    "viewer",
]


class UserCreate(BaseModel):
    username: str = Field(
        min_length=3,
        max_length=100,
    )

    display_name: str = Field(
        min_length=1,
        max_length=200,
    )

    password: str = Field(
        min_length=8,
        max_length=128,
    )

    role: UserRole = "viewer"

    @field_validator("username")
    @classmethod
    def normalize_username(
        cls,
        value: str,
    ) -> str:
        return value.strip().lower()


class UserUpdate(BaseModel):
    display_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
    )

    password: str | None = Field(
        default=None,
        min_length=8,
        max_length=128,
    )

    role: UserRole | None = None
    is_active: bool | None = None


class UserRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
    )

    id: str
    username: str
    display_name: str
    role: str
    is_active: bool

    created_at: datetime
    updated_at: datetime