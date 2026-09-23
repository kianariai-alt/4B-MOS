"""Redacted controlled-pilot readiness command.

A zero exit code means automated prerequisites passed. It never authorizes
clinical use; manual release gates remain outside this command.
"""
from __future__ import annotations

import argparse
import json
from typing import Sequence

from backend.app.core.config import settings
from backend.app.db.session import SessionLocal
from backend.app.services.pilot_readiness import ControlledPilotReadinessService


def render_text(report) -> str:
    lines = [f"controlled pilot gate: {report.status.upper()}"]
    lines.extend(
        f"[{item.status.upper()}] {item.name}: {item.code}"
        for item in report.automated_checks
    )
    lines.extend(
        f"[MANUAL_REQUIRED] {item.name}: {item.code}"
        for item in report.manual_gates
    )
    lines.extend(f"[WARNING] {warning}" for warning in report.warnings)
    lines.append("[AUTHORIZATION] controlled_pilot_authorized=false")
    return "\n".join(lines)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run redacted automated prerequisites for a controlled 4B-MOS "
            "pilot. This does not authorize clinical use."
        ),
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
        report = ControlledPilotReadinessService.build(db, settings)

    if args.output_format == "json":
        print(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True))
    else:
        print(render_text(report))

    return 0 if report.status == "automated_prerequisites_passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
