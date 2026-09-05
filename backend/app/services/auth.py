from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

from backend.app.core.config import settings
from backend.app.db.transactions import _is_contention
from backend.app.db.account_transactions import lock_accounts, AccountWriteConflictError

from backend.app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from backend.app.models.user import User
from backend.app.repositories.user import UserRepository
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.services.account_audit import account_snapshot
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
            lock_accounts(db)
            if UserRepository.count(db) != 0:
                raise BootstrapAlreadyCompletedError("System bootstrap has already been completed.")
            user = User(
                username=payload.username, display_name=payload.display_name,
                password_hash=hash_password(payload.password), role="admin",
            )
            db.add(user)
            db.flush()
            AuditLogRepository.create(
                db, commit=False, entity_type="user", entity_id=user.id,
                event_type="admin_bootstrapped",
                event_data={"schema_version": 1, "source": "unauthenticated_bootstrap",
                            "after": account_snapshot(user)},
            )
            db.commit()
            return user
        except AccountWriteConflictError as error:
            db.rollback()
            raise BootstrapDisabledError(str(error)) from error
        except OperationalError as error:
            db.rollback()
            if _is_contention(error):
                raise BootstrapAlreadyCompletedError("Bootstrap is busy; reload before retrying.") from error
            raise
        except Exception:
            db.rollback()
            raise
