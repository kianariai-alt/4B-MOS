"""Transaction boundaries for top-level clinical service commands."""

from functools import wraps
from inspect import signature

from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from backend.app.models.treatment import Treatment
from backend.app.models.treatment_session import TreatmentSession


class ClinicalWriteConflictError(Exception):
    """The command could not acquire a consistent clinical write transaction."""


def _lock_treatment(db: Session, arguments: dict) -> None:
    # Never discard pending edits when refreshing a request's identity map.
    if db.new or db.dirty or db.deleted:
        raise RuntimeError("Clinical commands require a Session without pending writes.")
    if "treatment_id" in arguments:
        treatment_id = arguments["treatment_id"]
    else:
        treatment_id = (
            select(TreatmentSession.treatment_id)
            .where(TreatmentSession.id == arguments["session_id"])
            .scalar_subquery()
        )
    # A no-op UPDATE acquires the writer lock on SQLite and a row lock on
    # PostgreSQL. SELECT FOR UPDATE alone would provide no lock on SQLite.
    # Explicit updated_at suppresses the model's onupdate default.
    db.execute(
        update(Treatment)
        .where(Treatment.id == treatment_id)
        .values(id=Treatment.id, updated_at=Treatment.updated_at)
        .execution_options(synchronize_session=False)
    )
    # Authentication/read dependencies may already have loaded stale objects.
    # Validate only after locking, with freshly loaded state and relationships.
    db.expire_all()


def _is_contention(error: OperationalError) -> bool:
    original = error.orig
    sqlite_code = getattr(original, "sqlite_errorcode", None)
    return (
        (sqlite_code is not None and sqlite_code & 0xFF in {5, 6})
        or getattr(original, "sqlstate", None) in {"40001", "40P01", "55P03"}
        or getattr(original, "pgcode", None) in {"40001", "40P01", "55P03"}
    )


def atomic_write(command):
    """Commit a service command and its audit events together.

    The command owns the request-scoped Session transaction, including an
    existing autobegun read transaction. Repositories called by it must flush
    rather than commit. Do not nest these top-level commands or use them with
    a Session containing unrelated pending writes. All protected commands must
    accept treatment_id or session_id. The parent lock is held through the
    clinical write AND its audit commit. SQLite serializes database writers;
    PostgreSQL serializes writers for the same treatment. Other write services
    and direct SQL do not automatically participate in this protocol.
    """
    parameters = signature(command)
    if not {"treatment_id", "session_id"}.intersection(parameters.parameters):
        raise TypeError("Clinical commands need treatment_id or session_id.")

    @wraps(command)
    def wrapped(db: Session, *args, **kwargs):
        try:
            _lock_treatment(db, parameters.bind(db, *args, **kwargs).arguments)
            result = command(db, *args, **kwargs)
            db.commit()
            return result
        except OperationalError as error:
            db.rollback()
            if _is_contention(error):
                raise ClinicalWriteConflictError(
                    "Another request changed or locked this treatment. "
                    "Reload its current state before retrying."
                ) from error
            raise
        except Exception:
            db.rollback()
            raise

    return wrapped
