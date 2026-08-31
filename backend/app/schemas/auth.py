from pydantic import (
    BaseModel,
    Field,
    field_validator,
)

from backend.app.schemas.user import UserRead


class LoginRequest(BaseModel):
    username: str = Field(
        min_length=3,
        max_length=100,
    )

    password: str = Field(
        min_length=1,
        max_length=128,
    )

    @field_validator("username")
    @classmethod
    def normalize_username(
        cls,
        value: str,
    ) -> str:
        return value.strip().lower()


class BootstrapAdminRequest(BaseModel):
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

    @field_validator("username")
    @classmethod
    def normalize_username(
        cls,
        value: str,
    ) -> str:
        return value.strip().lower()


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class CurrentUserResponse(BaseModel):
    user: UserRead