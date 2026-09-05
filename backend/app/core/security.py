from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash

from backend.app.core.config import settings


password_hash = PasswordHash.recommended()


def hash_password(
    password: str,
) -> str:
    return password_hash.hash(
        password
    )


def verify_password(
    plain_password: str,
    hashed_password: str,
) -> bool:
    return password_hash.verify(
        plain_password,
        hashed_password,
    )


def create_access_token(
    *,
    subject: str,
    auth_version: int = 0,
    expires_minutes: int | None = None,
) -> str:
    now = datetime.now(timezone.utc)

    expire = now + timedelta(
        minutes=(
            settings.ACCESS_TOKEN_EXPIRE_MINUTES
            if expires_minutes is None else expires_minutes
        )
    )

    payload = {
        "sub": subject,
        "iat": now,
        "exp": expire,
        "ver": auth_version,
    }

    return jwt.encode(
        payload,
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_access_token(
    token: str,
) -> dict:
    return jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[
            settings.JWT_ALGORITHM
        ],
        options={"require": ["sub", "iat", "exp", "ver"]},
    )
