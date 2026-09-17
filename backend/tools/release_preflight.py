"""Read-only release preflight for a configured 4B-MOS environment.

This command intentionally reports only fixed check and warning codes. It does
not print connection URLs, exception messages, usernames, counts, secrets or
clinical records.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from typing import Literal, Sequence

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.core.config import Settings, settings
from backend.app.core.database_revision import EXPECTED_DATABASE_REVISION
from backend.app.core.readiness import database_readiness_issues
from backend.app.db.session import SessionLocal
from backend.app.models.user import User


CheckStatus = Literal["pass", "fail", "blocked"]


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    status: CheckStatus
    code: str


@dataclass(frozen=True)
class PreflightReport:
    status: Literal["ready", "not_ready"]
    application: str
    version: str
    expected_database_revision: str
    database_dialect: str
    checks: tuple[PreflightCheck, ...]
    warnings: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def to_dict(self) -> dict:
        return asdict(self)


def _runtime_check(config: Settings) -> PreflightCheck:
    if (
        config.ENVIRONMENT == "production"
        and not config.DEBUG
        and not config.BOOTSTRAP_ENABLED
    ):
        return PreflightCheck(
            name="runtime_configuration",
            status="pass",
            code="production_runtime_safe",
        )
    return PreflightCheck(
        name="runtime_configuration",
        status="fail",
        code="production_runtime_required",
    )


def build_preflight_report(
    db: Session,
    config: Settings,
) -> PreflightReport:
    """Inspect release prerequisites without performing database writes."""

    checks: list[PreflightCheck] = [_runtime_check(config)]
    dialect = db.get_bind().dialect.name
    database_ready = False

    try:
        issues = database_readiness_issues(db)
        database_ready = not issues
        checks.append(
            PreflightCheck(
                name="database_schema",
                status="pass" if database_ready else "fail",
                code="database_schema_ready" if database_ready else issues[0],
            )
        )
    except SQLAlchemyError:
        db.rollback()
        checks.append(
            PreflightCheck(
                name="database_schema",
                status="fail",
                code="database_unavailable_or_uninitialized",
            )
        )

    if database_ready:
        try:
            active_admin_exists = (
                db.scalar(
                    select(func.count())
                    .select_from(User)
                    .where(User.role == "admin", User.is_active.is_(True))
                )
                or 0
            ) > 0
            checks.append(
                PreflightCheck(
                    name="active_administrator",
                    status="pass" if active_admin_exists else "fail",
                    code=(
                        "active_administrator_present"
                        if active_admin_exists
                        else "active_administrator_missing"
                    ),
                )
            )
        except SQLAlchemyError:
            db.rollback()
            checks.append(
                PreflightCheck(
                    name="active_administrator",
                    status="fail",
                    code="administrator_check_failed",
                )
            )
    else:
        checks.append(
            PreflightCheck(
                name="active_administrator",
                status="blocked",
                code="database_schema_not_ready",
            )
        )

    warnings: tuple[str, ...] = ()
    if dialect == "sqlite":
        warnings = ("sqlite_serializes_database_writers",)

    ready = all(check.status == "pass" for check in checks)
    return PreflightReport(
        status="ready" if ready else "not_ready",
        application=config.PROJECT_NAME,
        version=config.PROJECT_VERSION,
        expected_database_revision=EXPECTED_DATABASE_REVISION,
        database_dialect=dialect,
        checks=tuple(checks),
        warnings=warnings,
    )


def render_text(report: PreflightReport) -> str:
    lines = [f"release preflight: {report.status.upper()}"]
    lines.extend(
        f"[{check.status.upper()}] {check.name}: {check.code}"
        for check in report.checks
    )
    lines.extend(f"[WARNING] {warning}" for warning in report.warnings)
    return "\n".join(lines)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run redacted, read-only release prerequisite checks.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        dest="output_format",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    with SessionLocal() as db:
        report = build_preflight_report(db, settings)

    if args.output_format == "json":
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print(render_text(report))
    return 0 if report.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
