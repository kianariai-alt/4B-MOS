"""Serialize account administration before authorization and invariant checks."""
from functools import wraps

from sqlalchemy import false, inspect, select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from backend.app.db.transactions import _is_contention
from backend.app.models.user import User


class AccountWriteConflictError(Exception):
    pass


class AccountAuthorizationError(Exception):
    pass


def lock_accounts(db: Session):
    if db.new or db.dirty or db.deleted:
        raise RuntimeError("Account commands require a Session without pending writes.")
    connection = db.connection()
    if connection.dialect.name == "sqlite":
        db.execute(update(User).where(false()).values(updated_at=User.updated_at))
    elif connection.dialect.name == "postgresql":
        # A table lock alone cannot refresh a pre-existing repeatable-read
        # snapshot. Refuse unsupported isolation rather than count stale admins.
        if connection.get_isolation_level() != "READ COMMITTED":
            raise AccountWriteConflictError("Account administration requires READ COMMITTED isolation.")
        db.execute(text("LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE"))
    else:
        raise AccountWriteConflictError("Account administration is unsupported for this database.")
    db.expire_all()


def lock_login_account(db: Session, user_id: str) -> User | None:
    """Lock one login account while allowing unrelated PostgreSQL logins.

    SQLite has database-level writer serialization. PostgreSQL first takes a
    compatible ROW EXCLUSIVE table lock so account-administration's stronger
    table lock and this per-row lock always follow a deterministic order.
    """
    if db.new or db.dirty or db.deleted:
        raise RuntimeError("Login commands require a Session without pending writes.")
    connection = db.connection()
    if connection.dialect.name == "sqlite":
        db.execute(
            update(User)
            .where(User.id == user_id)
            .values(updated_at=User.updated_at)
        )
    elif connection.dialect.name == "postgresql":
        if connection.get_isolation_level() != "READ COMMITTED":
            raise AccountWriteConflictError(
                "Login throttling requires READ COMMITTED isolation."
            )
        # Compatible across login transactions, but ordered before the
        # SHARE ROW EXCLUSIVE lock used by account administration.
        db.execute(text("LOCK TABLE users IN ROW EXCLUSIVE MODE"))
    else:
        raise AccountWriteConflictError(
            "Login throttling is unsupported for this database."
        )
    db.expire_all()
    statement = (
        select(User)
        .where(User.id == user_id)
        .execution_options(populate_existing=True)
    )
    if connection.dialect.name == "postgresql":
        statement = statement.with_for_update()
    return db.scalar(statement)


def require_current_admin(db: Session, actor: User | None):
    # None is for trusted in-process calls only. HTTP mutation routes always
    # supply the authenticated actor and still retain their initial role gate.
    if actor is not None:
        identity = inspect(actor).identity
        current = db.get(User, identity[0] if identity else actor.id)
        if current is None or not current.is_active or current.role != "admin":
            raise AccountAuthorizationError("Administrator access is no longer active.")


def atomic_account_write(command):
    @wraps(command)
    def wrapped(db: Session, *args, **kwargs):
        try:
            lock_accounts(db)
            result = command(db, *args, **kwargs)
            db.commit()
            return result
        except OperationalError as error:
            db.rollback()
            if _is_contention(error):
                raise AccountWriteConflictError("Another request is changing accounts. Reload before retrying.") from error
            raise
        except Exception:
            db.rollback()
            raise
    return wrapped
