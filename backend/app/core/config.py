from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ENVIRONMENT: Literal["development", "test", "production"] = "development"
    BOOTSTRAP_ENABLED: bool = True
    PROJECT_NAME: str = "4B-MOS"
    PROJECT_VERSION: str = "0.1.0"

    API_V1_PREFIX: str = "/api/v1"

    DEBUG: bool = True

    HOST: str = "127.0.0.1"
    PORT: int = 8000

    DATABASE_URL: str = "sqlite:///./4bmos.db"

    SECRET_KEY: str = (
        "4bmos-development-secret-change-before-production"
    )

    JWT_ALGORITHM: Literal["HS256"] = "HS256"

    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60, ge=1, le=1440)
    CLINIC_TIMEZONE: str = "Asia/Tehran"

    @model_validator(mode="after")
    def validate_production(self):
        if self.ENVIRONMENT == "production":
            if self.DEBUG:
                raise ValueError("DEBUG must be disabled in production.")
            if self.BOOTSTRAP_ENABLED:
                raise ValueError("Public bootstrap must be disabled in production.")
            if (len(self.SECRET_KEY) < 32 or len(set(self.SECRET_KEY)) < 10
                    or "change" in self.SECRET_KEY.lower()
                    or "development" in self.SECRET_KEY.lower()):
                raise ValueError("Production requires a separately generated strong SECRET_KEY.")
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
        hide_input_in_errors=True,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
