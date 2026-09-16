from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

from backend.app.core.config import settings
from backend.app.db.transactions import _is_contention
from backend.app.db.account_transactions import (
    AccountWriteConflictError,
    lock_accounts,
    lock_login_account,
)

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


class AuthenticationTemporarilyUnavailableError(Exception):
    pass


class BootstrapAlreadyCompletedError(Exception):
    pass


class BootstrapDisabledError(Exception):
    pass


GENERIC_LOGIN_FAILURE_MESSAGE = "Invalid username or password."

# Unknown usernames still execute the same password verifier as known accounts.
# This is a fixed non-secret hash whose plaintext is never accepted by the
# application; changing it is not a credential rotation.
DUMMY_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$"
    "rSiFl1cY6kvUMpuRd4s/Dg$"
    "UW+aB0Sae5XGj9YY4hR+/5aOKM2fkp65VgfuQuAgJ/s"
)


class AuthService:
    @staticmethod
    def _as_utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _clear_login_throttle(user: User) -> None:
        user.failed_login_count = 0
        user.failed_login_window_started_at = None
        user.login_locked_until = None

    @staticmethod
    def _record_login_failure(
        db: Session,
        user: User,
        *,
        now: datetime,
    ) -> None:
        window_started = AuthService._as_utc(
            user.failed_login_window_started_at
        )
        locked_until = AuthService._as_utc(user.login_locked_until)

        # An expired lock starts a fresh observation window. Otherwise one
        # more failure immediately re-locks the account forever.
        if locked_until is not None and locked_until <= now:
            AuthService._clear_login_throttle(user)
            window_started = None

        window = timedelta(seconds=settings.LOGIN_FAILURE_WINDOW_SECONDS)
        if window_started is None or now - window_started >= window:
            user.failed_login_count = 1
            user.failed_login_window_started_at = now
        else:
            user.failed_login_count += 1

        account_locked = user.failed_login_count >= settings.LOGIN_MAX_FAILURES
        if account_locked:
            user.login_locked_until = now + timedelta(
                seconds=settings.LOGIN_LOCKOUT_SECONDS
            )

        db.add(user)
        AuditLogRepository.create(
            db,
            commit=False,
            entity_type="user",
            entity_id=user.id,
            event_type="login_failed",
            event_data={
                "schema_version": 1,
                "failure_count": user.failed_login_count,
                "account_locked": account_locked,
            },
        )

    @staticmethod
    def authenticate(
        db: Session,
        *,
        username: str,
        password: str,
        now: datetime | None = None,
    ) -> User:
        current_time = AuthService._as_utc(now) or datetime.now(timezone.utc)
        try:
            candidate = UserRepository.get_by_username(db, username)
            if candidate is None:
                # Do equivalent password-hash work for unknown usernames but
                # create no durable row containing attacker-controlled input.
                verify_password(password, DUMMY_PASSWORD_HASH)
                db.rollback()
                raise InvalidCredentialsError(GENERIC_LOGIN_FAILURE_MESSAGE)

            # Serialize only this account on PostgreSQL. The shared lock order
            # also prevents password reset from racing the refreshed hash.
            user = lock_login_account(db, candidate.id)
            if user is None:
                verify_password(password, DUMMY_PASSWORD_HASH)
                db.rollback()
                raise InvalidCredentialsError(GENERIC_LOGIN_FAILURE_MESSAGE)

            password_matches = verify_password(password, user.password_hash)

            locked_until = AuthService._as_utc(user.login_locked_until)
            if locked_until is not None and locked_until > current_time:
                # Do not extend the lock or create unbounded audit rows while
                # the account is already locked.
                db.rollback()
                raise InvalidCredentialsError(GENERIC_LOGIN_FAILURE_MESSAGE)

            if not password_matches or not user.is_active:
                AuthService._record_login_failure(
                    db,
                    user,
                    now=current_time,
                )
                db.commit()
                raise InvalidCredentialsError(GENERIC_LOGIN_FAILURE_MESSAGE)

            previous_failure_count = user.failed_login_count
            previously_locked = user.login_locked_until is not None
            had_throttle_state = (
                previous_failure_count != 0
                or user.failed_login_window_started_at is not None
                or previously_locked
            )
            if had_throttle_state:
                AuthService._clear_login_throttle(user)
                db.add(user)
                AuditLogRepository.create(
                    db,
                    commit=False,
                    entity_type="user",
                    entity_id=user.id,
                    event_type="login_throttle_cleared",
                    event_data={
                        "schema_version": 1,
                        "reason": "successful_login",
                        "previous_failure_count": previous_failure_count,
                        "previously_locked": previously_locked,
                    },
                )

            # Even an unchanged success must end the explicit account-lock
            # transaction before the token is created.
            db.commit()
            return user
        except InvalidCredentialsError:
            if db.in_transaction():
                db.rollback()
            raise
        except AccountWriteConflictError as error:
            db.rollback()
            raise AuthenticationTemporarilyUnavailableError(
                "Authentication is temporarily unavailable."
            ) from error
        except OperationalError as error:
            db.rollback()
            if _is_contention(error):
                raise AuthenticationTemporarilyUnavailableError(
                    "Authentication is temporarily unavailable."
                ) from error
            raise
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def create_token(
        user: User,
    ) -> str:
        return create_access_token(
            subject=user.id,
            auth_version=user.auth_version,
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
