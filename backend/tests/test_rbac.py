import pytest
from fastapi import HTTPException

from backend.app.api.dependencies import require_roles
from backend.app.models.user import User


def make_user(
    role: str,
) -> User:
    return User(
        username=f"{role}_user",
        display_name=f"{role.title()} User",
        password_hash="not-used-in-this-test",
        role=role,
        is_active=True,
    )


def test_admin_role_is_allowed():
    dependency = require_roles(
        "admin",
    )

    user = make_user(
        "admin"
    )

    result = dependency(
        current_user=user
    )

    assert result is user


def test_disallowed_role_returns_403():
    dependency = require_roles(
        "admin",
    )

    user = make_user(
        "viewer"
    )

    with pytest.raises(
        HTTPException
    ) as exc_info:
        dependency(
            current_user=user
        )

    assert exc_info.value.status_code == 403


def test_multiple_roles_are_supported():
    dependency = require_roles(
        "admin",
        "physician",
        "nurse",
    )

    user = make_user(
        "physician"
    )

    result = dependency(
        current_user=user
    )

    assert result.role == "physician"