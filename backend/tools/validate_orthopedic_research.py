"""Offline integrity checks for the inactive orthopaedic research catalogue.

No database, network, archive extraction, or knowledge-registry imports occur.
Passing this check establishes file integrity, never clinical or licence approval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse


SCHEMA_VERSION = "4b.orthopedic-research-catalog.v1"
MAX_CATALOG_BYTES = 2 * 1024 * 1024
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 500
SOURCE_TYPES = {
    "guideline", "systematic_review", "randomized_trial",
    "observational_study", "regulatory", "consensus", "textbook", "other",
}


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source_count: int = 0
    verified_artifacts: int = 0
    clinical_activation: bool = False

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, **asdict(self)}


def _https_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlparse(value)
        return (
            parsed.scheme == "https" and bool(parsed.hostname)
            and parsed.username is None and parsed.password is None
        )
    except ValueError:
        return False


def _date_or_null(value: Any) -> bool:
    if value is None:
        return True
    try:
        return isinstance(value, str) and date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _timestamp(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.tzinfo is not None and parsed.utcoffset() is not None
    except ValueError:
        return False


def _safe_path(value: Any) -> str | None:
    """Use portable relative paths, including when validating on Windows."""
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        return None
    path = PurePosixPath(value)
    parts = value.split("/")
    windows_devices = {"CON", "PRN", "AUX", "NUL"} | {
        f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
    }
    if (
        path.is_absolute() or "\x00" in value
        or any(part in {"", ".", ".."} for part in parts)
        or any(part.endswith((".", " ")) for part in parts)
        or any(part.split(".")[0].upper() in windows_devices for part in parts)
    ):
        return None
    return path.as_posix()


def _digest(stream) -> str:
    sha = hashlib.sha256()
    total = 0
    while chunk := stream.read(1024 * 1024):
        total += len(chunk)
        if total > MAX_ARTIFACT_BYTES:
            raise ValueError("artifact exceeds 64 MiB limit")
        sha.update(chunk)
    return sha.hexdigest()


def _zip_members(
    archive: zipfile.ZipFile, report: ValidationReport,
) -> dict[str, zipfile.ZipInfo]:
    members = archive.infolist()
    if len(members) > MAX_ARCHIVE_MEMBERS:
        report.errors.append("archive: more than 500 members")
        return {}
    if sum(member.file_size for member in members) > MAX_ARCHIVE_BYTES:
        report.errors.append("archive: uncompressed size exceeds 256 MiB")
        return {}
    files: dict[str, zipfile.ZipInfo] = {}
    seen: set[str] = set()
    for member in members:
        name = member.filename.rstrip("/") if member.is_dir() else member.filename
        safe = _safe_path(name)
        if safe is None:
            report.errors.append("archive: unsafe member path")
            continue
        # Windows filenames are case insensitive; ambiguity is invalid everywhere.
        if safe.casefold() in seen:
            report.errors.append(f"archive: duplicate member {safe}")
            continue
        seen.add(safe.casefold())
        if stat.S_ISLNK(member.external_attr >> 16):
            report.errors.append(f"archive: symlink member {safe}")
        elif member.flag_bits & 1:
            report.errors.append(f"archive: encrypted member {safe}")
        elif member.file_size > MAX_ARTIFACT_BYTES:
            report.errors.append(f"archive: member exceeds 64 MiB: {safe}")
        elif not member.is_dir():
            files[safe] = member
    return files


def validate_catalog(
    catalog: Any,
    *,
    root: Path | None = None,
    archive_path: Path | None = None,
    require_artifacts: bool = False,
) -> ValidationReport:
    """Validate v1 metadata and every declared artifact against local bytes.

    With no local artifacts, metadata can pass with warnings. Use
    ``require_artifacts=True`` to require at least one verified file per source.
    An archive is read in place; it is never extracted or modified.
    """
    report = ValidationReport()
    if not isinstance(catalog, dict):
        report.errors.append("catalog must be a JSON object")
        return report
    if catalog.get("schema_version") != SCHEMA_VERSION:
        report.errors.append("unsupported schema_version")
    for key in ("clinical_activation", "registry_imported", "commercial_retrieval"):
        if catalog.get(key) is not False:
            report.errors.append(f"{key} must be explicitly false")
    if catalog.get("status") != "inactive_research":
        report.errors.append("status must be inactive_research")
    if not _date_or_null(catalog.get("cataloged_on")) or not catalog.get("cataloged_on"):
        report.errors.append("cataloged_on must be an ISO date")
    claimed_archive = catalog.get("previous_archive")
    if not isinstance(claimed_archive, dict):
        report.errors.append("previous_archive must describe the handoff archive")
    elif claimed_archive.get("local_status") == "not_available":
        if claimed_archive.get("sha256") is not None:
            report.errors.append("unavailable previous_archive cannot claim a SHA256")
    sources = catalog.get("sources")
    if not isinstance(sources, list) or not sources:
        report.errors.append("sources must be a nonempty list")
        return report
    report.source_count = len(sources)
    archive: zipfile.ZipFile | None = None
    files: dict[str, zipfile.ZipInfo] = {}
    if archive_path is not None:
        try:
            archive = zipfile.ZipFile(archive_path)
            files = _zip_members(archive, report)
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            report.errors.append(f"archive cannot be read: {type(exc).__name__}")
            if archive is not None:
                archive.close()
            return report
    source_ids: set[str] = set()
    artifact_paths: set[str] = set()
    try:
        for index, source in enumerate(sources):
            label = f"source[{index}]"
            if not isinstance(source, dict):
                report.errors.append(f"{label}: must be an object")
                continue
            source_id = source.get("id")
            if not isinstance(source_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,99}", source_id):
                report.errors.append(f"{label}: invalid id")
            elif source_id in source_ids:
                report.errors.append(f"{label}: duplicate id {source_id}")
            else:
                source_ids.add(source_id)
                label = source_id
            if not isinstance(source.get("title"), str) or not source["title"].strip():
                report.errors.append(f"{label}: title required")
            if not isinstance(source.get("source_type"), str) or source["source_type"] not in SOURCE_TYPES:
                report.errors.append(f"{label}: invalid registry source_type")
            if source.get("knowledge_layer") not in ("base_reference", "current_evidence", "clinic_protocol"):
                report.errors.append(f"{label}: invalid knowledge_layer")
            if source.get("clinical_status") != "inactive":
                report.errors.append(f"{label}: clinical_status must be inactive")
            if source.get("registry_status") != "not_imported":
                report.errors.append(f"{label}: registry_status must be not_imported")
            if source.get("evidence_grade") != "ungraded":
                report.errors.append(f"{label}: research catalog cannot assign an evidence grade")
            if not _https_url(source.get("url")):
                report.errors.append(f"{label}: HTTPS source URL required")
            for key in ("publication_date", "last_reviewed_on"):
                if not _date_or_null(source.get(key)):
                    report.errors.append(f"{label}: invalid {key}")
            if not isinstance(source.get("applicability_limits"), list) or not source["applicability_limits"]:
                report.errors.append(f"{label}: applicability_limits required")
            license_review = source.get("license_review")
            if not isinstance(license_review, dict):
                report.errors.append(f"{label}: license_review required")
            else:
                if license_review.get("status") not in ("unverified", "permission_required"):
                    report.errors.append(f"{label}: licence approval is outside this research catalog")
                for key in ("commercial_retrieval_allowed", "image_reuse_allowed"):
                    if license_review.get(key) is not False:
                        report.errors.append(f"{label}: {key} must be explicitly false")
            artifacts = source.get("artifacts")
            if not isinstance(artifacts, list):
                report.errors.append(f"{label}: artifacts must be a list")
                continue
            expected_acquisition = "local_artifacts_declared" if artifacts else "unavailable_in_session"
            if source.get("acquisition_status") != expected_acquisition:
                report.errors.append(f"{label}: acquisition_status inconsistent with artifacts")
            if not artifacts:
                message = f"{label}: no local source artifact verified"
                (report.errors if require_artifacts else report.warnings).append(message)
            for artifact in artifacts:
                if not isinstance(artifact, dict):
                    report.errors.append(f"{label}: artifact must be an object")
                    continue
                path = _safe_path(artifact.get("path"))
                if path is None:
                    report.errors.append(f"{label}: unsafe artifact path")
                    continue
                if path.casefold() in artifact_paths:
                    report.errors.append(f"{label}: duplicate artifact path {path}")
                    continue
                artifact_paths.add(path.casefold())
                expected = artifact.get("sha256")
                if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
                    report.errors.append(f"{label}: invalid SHA256 for {path}")
                    continue
                if not _timestamp(artifact.get("acquired_at")):
                    report.errors.append(f"{label}: timezone-aware acquired_at required for {path}")
                    continue
                if not _https_url(artifact.get("source_url")):
                    report.errors.append(f"{label}: artifact source_url required for {path}")
                    continue
                try:
                    if archive is not None:
                        if path not in files:
                            report.errors.append(f"{label}: missing archive artifact {path}")
                            continue
                        with archive.open(files[path]) as stream:
                            actual = _digest(stream)
                    elif root is not None:
                        base = root.resolve()
                        candidate = (base / path).resolve()
                        if not candidate.is_relative_to(base):
                            report.errors.append(f"{label}: artifact escapes root {path}")
                            continue
                        if not candidate.is_file():
                            report.errors.append(f"{label}: missing local artifact {path}")
                            continue
                        with candidate.open("rb") as stream:
                            actual = _digest(stream)
                    else:
                        report.errors.append(f"{label}: --root or --archive required to verify {path}")
                        continue
                    if actual != expected:
                        report.errors.append(f"{label}: SHA256 mismatch for {path}")
                    else:
                        report.verified_artifacts += 1
                except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
                    report.errors.append(f"{label}: artifact unreadable {path}: {type(exc).__name__}")
    finally:
        if archive is not None:
            archive.close()
    report.warnings.append("Integrity checks do not establish licensing or clinical approval.")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    local = parser.add_mutually_exclusive_group()
    local.add_argument("--root", type=Path)
    local.add_argument("--archive", type=Path)
    parser.add_argument("--require-artifacts", action="store_true")
    args = parser.parse_args(argv)
    try:
        with args.catalog.open("rb") as stream:
            raw = stream.read(MAX_CATALOG_BYTES + 1)
        if len(raw) > MAX_CATALOG_BYTES:
            raise ValueError("catalog exceeds 2 MiB")
        catalog = json.loads(raw)
    except (OSError, ValueError) as exc:
        report = ValidationReport(errors=[f"catalog cannot be read: {type(exc).__name__}"])
    else:
        report = validate_catalog(
            catalog, root=args.root, archive_path=args.archive,
            require_artifacts=args.require_artifacts,
        )
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
