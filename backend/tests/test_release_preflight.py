import json

import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import Session

import backend.app.models
from backend.app.core.config import Settings
from backend.app.core.database_revision import EXPECTED_DATABASE_REVISION
from backend.app.db.base import Base
from backend.app.models.user import User
from backend.tools.release_preflight import build_preflight_report, render_text


def production_settings(**overrides):
    return Settings(
        _env_file=None,
        **{
            "ENVIRONMENT": "production",
            "DEBUG": False,
            "BOOTSTRAP_ENABLED": False,
            "SECRET_KEY": "TEST-ONLY-key-0123456789-ABCDEFGHIJKLMNOPQRSTUVWXYZ",
            **overrides,
        },
    )


@pytest.fixture
def preflight_database(tmp_path):
    database_path = tmp_path / "preflight.db"
    engine = create_engine(f"sqlite:///{database_path}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        )
        connection.execute(
            text("INSERT INTO alembic_version VALUES (:revision)"),
            {"revision": EXPECTED_DATABASE_REVISION},
        )

    with Session(engine) as db:
        yield db, database_path

    engine.dispose()


def add_admin(db: Session, *, active: bool = True) -> None:
    db.add(
        User(
            username="release-admin",
            display_name="Release Administrator",
            password_hash="not-a-real-password-hash",
            role="admin",
            is_active=active,
        )
    )
    db.commit()


def checks_by_name(report):
    return {check.name: check for check in report.checks}


def test_preflight_passes_without_mutating_or_disclosing_data(preflight_database):
    db, database_path = preflight_database
    add_admin(db)
    before = db.scalar(select(func.count()).select_from(User))

    report = build_preflight_report(db, production_settings())

    assert report.ready is True
    assert report.status == "ready"
    assert report.database_dialect == "sqlite"
    assert checks_by_name(report)["runtime_configuration"].status == "pass"
    assert checks_by_name(report)["database_schema"].status == "pass"
    assert checks_by_name(report)["active_administrator"].status == "pass"
    assert report.warnings == ("sqlite_serializes_database_writers",)
    assert db.scalar(select(func.count()).select_from(User)) == before

    rendered = json.dumps(report.to_dict()) + render_text(report)
    for sensitive in (
        "release-admin",
        "Release Administrator",
        "not-a-real-password-hash",
        str(database_path),
        production_settings().SECRET_KEY,
    ):
        assert sensitive not in rendered


def test_preflight_requires_production_runtime(preflight_database):
    db, _ = preflight_database
    add_admin(db)
    config = Settings(
        _env_file=None,
        ENVIRONMENT="development",
        DEBUG=True,
        BOOTSTRAP_ENABLED=True,
    )

    report = build_preflight_report(db, config)

    runtime = checks_by_name(report)["runtime_configuration"]
    assert report.ready is False
    assert runtime.status == "fail"
    assert runtime.code == "production_runtime_required"


@pytest.mark.parametrize("active", [False, None])
def test_preflight_requires_an_active_administrator(preflight_database, active):
    db, _ = preflight_database
    if active is not None:
        add_admin(db, active=active)

    report = build_preflight_report(db, production_settings())

    administrator = checks_by_name(report)["active_administrator"]
    assert report.ready is False
    assert administrator.status == "fail"
    assert administrator.code == "active_administrator_missing"


def test_preflight_fails_closed_on_wrong_revision(preflight_database):
    db, _ = preflight_database
    add_admin(db)
    db.execute(text("UPDATE alembic_version SET version_num = 'old-revision'"))
    db.commit()

    report = build_preflight_report(db, production_settings())

    schema = checks_by_name(report)["database_schema"]
    administrator = checks_by_name(report)["active_administrator"]
    assert report.ready is False
    assert schema.status == "fail"
    assert schema.code == "database_revision_mismatch"
    assert administrator.status == "blocked"
    assert administrator.code == "database_schema_not_ready"


def test_preflight_redacts_uninitialized_database_error(preflight_database):
    db, database_path = preflight_database
    db.execute(text("DROP TABLE alembic_version"))
    db.commit()

    report = build_preflight_report(db, production_settings())

    schema = checks_by_name(report)["database_schema"]
    assert report.ready is False
    assert schema.code == "database_unavailable_or_uninitialized"
    rendered = json.dumps(report.to_dict())
    assert "no such table" not in rendered.lower()
    assert str(database_path) not in rendered


def test_preflight_text_is_stable_and_machine_safe(preflight_database):
    db, _ = preflight_database
    add_admin(db)

    output = render_text(build_preflight_report(db, production_settings()))

    assert output.splitlines() == [
        "release preflight: READY",
        "[PASS] runtime_configuration: production_runtime_safe",
        "[PASS] database_schema: database_schema_ready",
        "[PASS] active_administrator: active_administrator_present",
        "[WARNING] sqlite_serializes_database_writers",
    ]
