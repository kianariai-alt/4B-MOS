"""An explicit allowlist; never serialize a User model or request wholesale."""
from backend.app.models.user import User


def account_snapshot(user: User) -> dict:
    return {
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "is_active": user.is_active,
    }
