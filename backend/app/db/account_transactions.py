"""Serialize account administration before authorization and invariant checks."""
from functools import wraps

from sqlalchemy import false, inspect, text, update
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
