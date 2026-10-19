from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
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
    DATABASE_LOCK_TIMEOUT_MS: int = Field(default=5000, ge=100, le=30000)

    SECRET_KEY: str = (
        "4bmos-development-secret-change-before-production"
    )

    JWT_ALGORITHM: Literal["HS256"] = "HS256"

    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60, ge=1, le=1440)
    LOGIN_MAX_FAILURES: int = Field(default=5, ge=2, le=20)
    LOGIN_FAILURE_WINDOW_SECONDS: int = Field(
        default=900,
        ge=60,
        le=86400,
    )
    LOGIN_LOCKOUT_SECONDS: int = Field(
        default=300,
        ge=30,
        le=86400,
    )
    CLINIC_TIMEZONE: str = "Asia/Tehran"
    PILOT_ENFORCEMENT_ENABLED: bool = False

    AUDIO_PIPELINE_ENABLED: bool = False
    PATIENT_PORTAL_ENABLED: bool = False
    PATIENT_PORTAL_ORIGIN: str = "http://127.0.0.1:8000"
    PATIENT_PORTAL_NAME: str = Field(default="کلینیک 4B", min_length=1, max_length=120)
    PATIENT_PORTAL_KEY: SecretStr | None = None
    PATIENT_PORTAL_QUESTION_BANKS: dict[str, str] = Field(default_factory=dict)
    AUDIO_ENCRYPTION_KEY: SecretStr | None = None
    AUDIO_KEY_ID: str = Field(default="audio-v1", min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    SPEECH_MODEL_DIRECTORY: str = ""
    SPEECH_MODEL_ID: str = Field(default="local-whisper", min_length=1, max_length=200)
    SPEECH_LEASE_SECONDS: int = Field(default=3600, ge=60, le=14400)

    @model_validator(mode="after")
    def validate_production(self):
        if self.PATIENT_PORTAL_ENABLED:
            import base64
            from urllib.parse import urlsplit
            try:
                portal_key = base64.b64decode(self.PATIENT_PORTAL_KEY.get_secret_value(), validate=True) if self.PATIENT_PORTAL_KEY else b""
            except ValueError:
                portal_key = b""
            if len(portal_key) != 32:
                raise ValueError("Patient portal requires a separate 32-byte base64 PATIENT_PORTAL_KEY.")
            origin = urlsplit(self.PATIENT_PORTAL_ORIGIN)
            if (origin.scheme not in {"http", "https"} or not origin.hostname
                    or origin.username or origin.password or origin.query or origin.fragment
                    or origin.path or self.PATIENT_PORTAL_ORIGIN.endswith("/")
                    or (origin.scheme == "http" and origin.hostname not in {"127.0.0.1", "localhost", "::1"})):
                raise ValueError("Portal origin must be an HTTPS origin or loopback HTTP origin, without a path.")
        if self.AUDIO_PIPELINE_ENABLED:
            import base64
            try:
                decoded=base64.b64decode(self.AUDIO_ENCRYPTION_KEY.get_secret_value(), validate=True) if self.AUDIO_ENCRYPTION_KEY else b""
            except ValueError:
                decoded=b""
            if len(decoded)!=32:
                raise ValueError("Enabled audio pipeline requires its own 32-byte base64 encryption key.")
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
