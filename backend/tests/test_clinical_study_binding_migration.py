"""Study-binding migration checks against disposable synthetic SQLite stores."""

from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import MetaData, Table, create_engine, event, inspect, select, text
from sqlalchemy.exc import IntegrityError

from backend.app.core.config import settings
from backend.app.core.database_revision import EXPECTED_DATABASE_REVISION


PARENT_REVISION = "b12f6c8d4a90"
BINDING_REVISION = "c24a7b9e0d13"
BINDINGS = "clinical_study_bindings"
REVIEWS = "clinical_study_binding_reviews"


def _table(engine, name):
    return Table(name, MetaData(), autoload_with=engine)


def _seed_existing_records(engine):
    """Write only synthetic rows to the freshly migrated temporary file."""
    stamp = datetime.now(timezone.utc)
    with engine.begin() as connection:
        connection.execute(_table(connection, "patients").insert(), {
            "id": "synthetic-patient", "patient_code": "SYNTHETIC-BINDING-MIGRATION",
            "first_name": "Synthetic", "last_name": "Fixture", "is_active": True,
            "created_at": stamp, "updated_at": stamp,
        })
        for identifier in ("source-author", "binding-author", "binding-reviewer"):
            connection.execute(_table(connection, "users").insert(), {
                "id": identifier, "username": identifier, "display_name": "Synthetic Fixture",
                "password_hash": "unused-synthetic-password-hash", "role": "physician",
                "is_active": True, "auth_version": 0, "failed_login_count": 0,
                "created_at": stamp, "updated_at": stamp,
            })
        connection.execute(_table(connection, "visits").insert(), {
            "id": "synthetic-visit", "patient_id": "synthetic-patient", "status": "open",
            "visit_date": stamp, "created_at": stamp, "updated_at": stamp,
        })
        connection.execute(_table(connection, "paraclinical_reports").insert(), {
            "id": "synthetic-report", "visit_id": "synthetic-visit", "report_key": "SYNTHETIC-MRI",
            "version": 1, "status": "draft", "category": "imaging",
            "title": "Synthetic migration report", "conclusion": "Synthetic record only.",
            "content_sha256": "a" * 64, "created_by_user_id": "source-author",
            "row_version": 1, "created_at": stamp, "updated_at": stamp,
        })


@pytest.fixture
def study_binding_database(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'synthetic-study-binding-migration.db'}"
    monkeypatch.setattr(settings, "DATABASE_URL", url)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, PARENT_REVISION)
    engine = create_engine(url)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    try:
        _seed_existing_records(engine)
        command.upgrade(config, "head")
        engine.dispose()  # Reopen connections after Alembic's separate DDL connection.
        yield config, engine
    finally:
        engine.dispose()


def _binding_values(**changes):
    return {
        "id": "synthetic-binding", "visit_id": "synthetic-visit", "report_id": "synthetic-report",
        "report_key": "SYNTHETIC-MRI", "revision": 1, "request_key": "binding-key",
        "request_sha256": "b" * 64, "created_by_user_id": "binding-author",
        "created_at": datetime.now(timezone.utc), "sha256": "c" * 64,
        "payload": {"synthetic": True}, **changes,
    }


def _review_values(**changes):
    return {
        "id": "synthetic-review", "binding_id": "synthetic-binding", "sequence": 1,
        "request_key": "review-key", "physician_user_id": "binding-reviewer",
        "created_at": datetime.now(timezone.utc), "sha256": "d" * 64,
        "payload": {"synthetic": True}, **changes,
    }


def _assert_existing_records(connection):
    assert connection.scalar(text("SELECT patient_code FROM patients WHERE id='synthetic-patient'")) == "SYNTHETIC-BINDING-MIGRATION"
    assert connection.scalar(text("SELECT username FROM users WHERE id='source-author'")) == "source-author"
    assert connection.scalar(text("SELECT patient_id FROM visits WHERE id='synthetic-visit'")) == "synthetic-patient"
    row = connection.execute(text("SELECT report_key, version, content_sha256, status FROM paraclinical_reports WHERE id='synthetic-report'")).one()
    assert tuple(row) == ("SYNTHETIC-MRI", 1, "a" * 64, "draft")


def test_study_binding_upgrade_preserves_existing_rows_and_empty_round_trip(study_binding_database):
    config, engine = study_binding_database
    assert EXPECTED_DATABASE_REVISION == BINDING_REVISION
    command.check(config)
    inspector = inspect(engine)
    expected_foreign_keys = {
        BINDINGS: {("visit_id", "visits"), ("report_id", "paraclinical_reports"), ("created_by_user_id", "users")},
        REVIEWS: {("binding_id", BINDINGS), ("physician_user_id", "users")},
    }
    expected_unique_columns = {
        BINDINGS: {("visit_id", "request_key"), ("visit_id", "report_key", "revision")},
        REVIEWS: {("binding_id", "sequence"), ("binding_id", "request_key")},
    }
    for name in (BINDINGS, REVIEWS):
        foreign_keys = inspector.get_foreign_keys(name)
        assert {(fk["constrained_columns"][0], fk["referred_table"]) for fk in foreign_keys} == expected_foreign_keys[name]
        assert all(fk["options"]["ondelete"] == "RESTRICT" for fk in foreign_keys)
        assert {tuple(item["column_names"]) for item in inspector.get_unique_constraints(name)} == expected_unique_columns[name]
        assert all(not column["nullable"] for column in inspector.get_columns(name))
    assert {tuple(item["column_names"]) for item in inspector.get_indexes(BINDINGS)} == {("visit_id",)}
    assert {tuple(item["column_names"]) for item in inspector.get_indexes(REVIEWS)} == {("binding_id",)}
    with engine.connect() as connection:
        assert connection.scalar(text("PRAGMA foreign_keys")) == 1
        _assert_existing_records(connection)
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == BINDING_REVISION

    command.downgrade(config, PARENT_REVISION)
    engine.dispose()
    assert BINDINGS not in inspect(engine).get_table_names()
    assert REVIEWS not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        _assert_existing_records(connection)
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == PARENT_REVISION
    command.upgrade(config, "head")
    engine.dispose()
    command.check(config)
    with engine.connect() as connection:
        _assert_existing_records(connection)
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == BINDING_REVISION


def test_study_binding_constraints_and_restrict_foreign_keys_are_enforced(study_binding_database):
    _config, engine = study_binding_database
    bindings, reviews = _table(engine, BINDINGS), _table(engine, REVIEWS)
    with engine.begin() as connection:
        connection.execute(bindings.insert(), _binding_values())
        connection.execute(reviews.insert(), _review_values())

    invalid_bindings = [
        ({"visit_id": "missing-visit"}, "FOREIGN KEY"),
        ({"report_id": "missing-report"}, "FOREIGN KEY"),
        ({"created_by_user_id": "missing-author"}, "FOREIGN KEY"),
        ({"revision": 0}, "CHECK"),
        ({"request_sha256": "short"}, "CHECK"),
        ({"sha256": "short"}, "CHECK"),
        ({"request_key": "binding-key"}, "UNIQUE"),
        ({"revision": 1}, "UNIQUE"),
    ]
    invalid_reviews = [
        ({"binding_id": "missing-binding"}, "FOREIGN KEY"),
        ({"physician_user_id": "missing-physician"}, "FOREIGN KEY"),
        ({"sequence": 0}, "CHECK"),
        ({"sha256": "short"}, "CHECK"),
        ({"sequence": 1}, "UNIQUE"),
        ({"request_key": "review-key"}, "UNIQUE"),
    ]
    for index, (changes, message) in enumerate(invalid_bindings):
        values = _binding_values(id=f"invalid-binding-{index}", revision=2, request_key=f"invalid-{index}") | changes
        with pytest.raises(IntegrityError, match=message), engine.begin() as connection:
            connection.execute(bindings.insert(), values)
    for index, (changes, message) in enumerate(invalid_reviews):
        values = _review_values(id=f"invalid-review-{index}", sequence=2, request_key=f"invalid-{index}") | changes
        with pytest.raises(IntegrityError, match=message), engine.begin() as connection:
            connection.execute(reviews.insert(), values)

    for name, identifier in (
        ("paraclinical_reports", "synthetic-report"),
        ("users", "binding-author"), ("users", "binding-reviewer"),
        (BINDINGS, "synthetic-binding"),
    ):
        table = _table(engine, name)
        with pytest.raises(IntegrityError, match="FOREIGN KEY"), engine.begin() as connection:
            connection.execute(table.delete().where(table.c.id == identifier))
    with engine.connect() as connection:
        assert len(connection.execute(select(bindings)).all()) == 1
        assert len(connection.execute(select(reviews)).all()) == 1
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []


@pytest.mark.parametrize("evidence", ["binding", "review_only"])
def test_study_binding_downgrade_checks_all_evidence_before_any_ddl(study_binding_database, evidence):
    config, engine = study_binding_database
    bindings, reviews = _table(engine, BINDINGS), _table(engine, REVIEWS)
    if evidence == "binding":
        with engine.begin() as connection:
            connection.execute(bindings.insert(), _binding_values())
        evidence_table = bindings
    else:
        # Simulate an already-corrupt disposable store: even orphan review
        # evidence must prevent destructive DDL, independently of binding rows.
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
            connection.execute(reviews.insert(), _review_values())
            connection.commit()
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()
        evidence_table = reviews
    with engine.connect() as connection:
        before = connection.execute(select(evidence_table)).mappings().all()
    with pytest.raises(RuntimeError, match="study binding evidence would be lost"):
        command.downgrade(config, PARENT_REVISION)
    engine.dispose()
    assert {BINDINGS, REVIEWS} <= set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.execute(select(evidence_table)).mappings().all() == before
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == BINDING_REVISION
        _assert_existing_records(connection)
