"""Atomic write boundary for visit-scoped clinical records."""

from functools import wraps
from inspect import signature

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from backend.app.db.transactions import _is_contention
from backend.app.models.clinical_context import (
    ClinicalIntake,
    ParaclinicalReport,
)
from backend.app.models.treatment import Treatment
from backend.app.models.visit import Visit


class ClinicalRecordWriteConflictError(Exception):
    """A visit-scoped clinical record could not be written consistently."""


def _visit_identifier(arguments: dict):
    if "visit_id" in arguments:
        return arguments["visit_id"]
    if "intake_id" in arguments:
        return (
            select(ClinicalIntake.visit_id)
            .where(ClinicalIntake.id == arguments["intake_id"])
            .scalar_subquery()
        )
    if "report_id" in arguments:
        return (
            select(ParaclinicalReport.visit_id)
            .where(ParaclinicalReport.id == arguments["report_id"])
            .scalar_subquery()
        )
    if "treatment_id" in arguments:
        return (
            select(Treatment.visit_id)
            .where(Treatment.id == arguments["treatment_id"])
            .scalar_subquery()
        )
    raise TypeError(
        "Clinical record commands need visit_id, intake_id, report_id, "
        "or treatment_id."
    )


def _lock_visit(db: Session, arguments: dict) -> None:
    if db.new or db.dirty or db.deleted:
        raise RuntimeError(
            "Clinical record commands require a Session without pending writes."
        )
    connection = db.connection()
    if connection.dialect.name not in {"sqlite", "postgresql"}:
        raise ClinicalRecordWriteConflictError(
            "Clinical record writes are unsupported for this database."
        )
    if (
        connection.dialect.name == "postgresql"
        and connection.get_isolation_level() != "READ COMMITTED"
    ):
        raise ClinicalRecordWriteConflictError(
            "Clinical record writes require READ COMMITTED isolation."
        )
    visit_id = _visit_identifier(arguments)
    # The no-op update acquires SQLite's writer lock and PostgreSQL's row lock.
    # Preserve updated_at so documentation writes do not mutate visit metadata.
    db.execute(
        update(Visit)
        .where(Visit.id == visit_id)
        .values(id=Visit.id, updated_at=Visit.updated_at)
        .execution_options(synchronize_session=False)
    )
    db.expire_all()


def clinical_record_write(command):
    """Serialize a clinical record mutation and its audit events by visit."""

    parameters = signature(command)
    if not {
        "visit_id",
        "intake_id",
        "report_id",
        "treatment_id",
    }.intersection(parameters.parameters):
        raise TypeError(
            "Clinical record commands need visit_id, intake_id, report_id, "
            "or treatment_id."
        )

    @wraps(command)
    def wrapped(db: Session, *args, **kwargs):
        try:
            arguments = parameters.bind(db, *args, **kwargs).arguments
            _lock_visit(db, arguments)
            result = command(db, *args, **kwargs)
            db.commit()
            return result
        except OperationalError as error:
            db.rollback()
            if _is_contention(error):
                raise ClinicalRecordWriteConflictError(
                    "Another request changed or locked this visit. "
                    "Reload its clinical context before retrying."
                ) from error
            raise
        except (IntegrityError, StaleDataError) as error:
            db.rollback()
            raise ClinicalRecordWriteConflictError(
                "The clinical record conflicts with another write; reload and retry."
            ) from error
        except Exception:
            db.rollback()
            raise

    return wrapped
