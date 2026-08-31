from sqlalchemy.orm import Session

from backend.app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from backend.app.models.user import User
from backend.app.repositories.user import UserRepository
from backend.app.schemas.auth import BootstrapAdminRequest


class InvalidCredentialsError(Exception):
    pass


class InactiveUserError(Exception):
    pass


class BootstrapAlreadyCompletedError(Exception):
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

    @staticmethod
    def bootstrap_admin(
        db: Session,
        payload: BootstrapAdminRequest,
    ) -> User:
        user_count = UserRepository.count(
            db
        )

        if user_count != 0:
            raise BootstrapAlreadyCompletedError(
                "System bootstrap has already been completed."
            )

        hashed_password = hash_password(
            payload.password
        )

        return UserRepository.create(
            db,
            username=payload.username,
            display_name=payload.display_name,
            password_hash=hashed_password,
            role="admin",
        )