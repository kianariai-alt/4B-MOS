from sqlalchemy.orm import Session
from sqlalchemy import false, text, update
from sqlalchemy.exc import OperationalError

from backend.app.core.config import settings
from backend.app.db.transactions import _is_contention

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


class BootstrapDisabledError(Exception):
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
        if settings.ENVIRONMENT == "production" or not settings.BOOTSTRAP_ENABLED:
            raise BootstrapDisabledError("Administrator bootstrap is disabled.")
        try:
            if db.new or db.dirty or db.deleted:
                raise RuntimeError("Bootstrap requires a clean request Session.")
            dialect = db.get_bind().dialect.name
            if dialect == "sqlite":
                # Even an empty UPDATE obtains SQLite's database writer lock.
                db.execute(update(User).where(false()).values(updated_at=User.updated_at))
            elif dialect == "postgresql":
                # There is no user row to lock on an empty database.
                db.execute(text("LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE"))
            else:
                raise BootstrapDisabledError("Bootstrap is unsupported for this database.")
            if UserRepository.count(db) != 0:
                raise BootstrapAlreadyCompletedError("System bootstrap has already been completed.")
            user = User(
                username=payload.username, display_name=payload.display_name,
                password_hash=hash_password(payload.password), role="admin",
            )
            db.add(user)
            db.flush()
            db.commit()
            return user
        except OperationalError as error:
            db.rollback()
            if _is_contention(error):
                raise BootstrapAlreadyCompletedError("Bootstrap is busy; reload before retrying.") from error
            raise
        except Exception:
            db.rollback()
            raise
