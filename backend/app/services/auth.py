from sqlalchemy.orm import Session

from backend.app.core.security import (
    create_access_token,
    verify_password,
)
from backend.app.models.user import User
from backend.app.repositories.user import UserRepository


class InvalidCredentialsError(Exception):
    pass


class InactiveUserError(Exception):
    pass


class AuthService:
    @staticmethod
    def authenticate(
        db: Session,
        *,
        username: str,
        password: str,
    ) -> User:
        user = UserRepository.get_by_username(
            db,
            username,
        )

        if user is None:
            raise InvalidCredentialsError(
                "Invalid username or password."
            )

        if not verify_password(
            password,
            user.password_hash,
        ):
            raise InvalidCredentialsError(
                "Invalid username or password."
            )

        if not user.is_active:
            raise InactiveUserError(
                "User account is inactive."
            )

        return user

    @staticmethod
    def create_token(
        user: User,
    ) -> str:
        return create_access_token(
            subject=user.id,
        )