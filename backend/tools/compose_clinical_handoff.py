"""Compose audited specialist sources in a disposable synthetic test directory.

No git merge, clinical deployment, Registry import or remote I/O is performed.
Only manifest-pinned new files are copied; current integration files are kept.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess


MANIFEST_PATH = "backend/compatibility/specialist_pins.json"
IGNORED_DIRECTORIES = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
                       ".venv", "venv", "node_modules", ".handoff-sources"}
ALLOWED_PREFIXES = (
    "backend/app/schemas/", "backend/app/services/", "backend/app/knowledge/",
    "backend/app/imaging_intelligence/", "backend/app/decision_intelligence/",
    "backend/tools/", "backend/tests/imaging_intelligence/", "docs/contracts/", "docs/examples/",
)
ALLOWED_TESTS = {"backend/tests/test_imaging_integration_freshness.py",
                 "backend/tests/test_orthopedic_questions.py", "backend/tests/test_orthopedic_review.py"}
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024


class CompositionError(ValueError):
    """Only static error codes; never include source paths or medical payloads."""


def _fail(code):
    raise CompositionError(code)


def _digest(value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def _relative_path(value):
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        _fail("invalid_manifest_path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {".", ".."} for part in value.split("/")):
        _fail("invalid_manifest_path")
    if path.as_posix() != value or ".git" in path.parts:
        _fail("invalid_manifest_path")
    return value


def _no_symlinks(path):
    for item in (path, *path.parents):
        if item.is_symlink():
            _fail("source_symlink_forbidden")


def _root(path):
    path = Path(path).absolute()
    _no_symlinks(path)
    if not path.is_dir():
        _fail("source_root_unavailable")
    return path.resolve(strict=True)


def _ignored(path):
    return (any(part in IGNORED_DIRECTORIES for part in path.parts) or path.name == ".env"
            or path.name.endswith((".pyc", ".db", ".sqlite", ".sqlite3", "-wal", "-shm")))


def _read(root, relative):
    relative = _relative_path(relative)
    path = root / relative
    _no_symlinks(path)
    if not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
        _fail("source_file_unavailable")
    if not path.resolve(strict=True).is_relative_to(root):
        _fail("source_path_outside_root")
    if path.stat().st_size > MAX_FILE_BYTES:
        _fail("source_size_limit_exceeded")
    with path.open("rb") as handle:
        data = handle.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        _fail("source_size_limit_exceeded")
    return data


def _git(root, *arguments):
    result = subprocess.run(["git", "-C", str(root), *arguments], stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, check=False, timeout=10)
    if result.returncode:
        _fail("git_revision_not_verified")
    return result.stdout


def _manifest(value):
    if (not isinstance(value, dict)
            or set(value) != {"manifest_version", "integration_base_revision", "protected_integration_paths", "producers"}
            or value["manifest_version"] != "1.0.0"
            or not re.fullmatch(r"[0-9a-f]{40}", value["integration_base_revision"])):
        _fail("invalid_pin_manifest")
    producers = value["producers"]
    if not isinstance(producers, dict) or set(producers) != {"imaging", "orthopedic"}:
        _fail("invalid_pin_manifest")
    protected = value["protected_integration_paths"]
    if not isinstance(protected, list) or not protected or len(set(protected)) != len(protected):
        _fail("invalid_pin_manifest")
    for path in protected:
        _relative_path(path)
    seen = set()
    for producer in producers.values():
        if (not isinstance(producer, dict) or set(producer) != {"revision", "files"}
                or not re.fullmatch(r"[0-9a-f]{40}", producer["revision"])
                or not isinstance(producer["files"], list) or not producer["files"]):
            _fail("invalid_pin_manifest")
        for entry in producer["files"]:
            if (not isinstance(entry, dict) or set(entry) != {"path", "git_blob_sha1"}
                    or not isinstance(entry["git_blob_sha1"], str)
                    or not re.fullmatch(r"[0-9a-f]{40}", entry["git_blob_sha1"])):
                _fail("invalid_pin_manifest")
            path = _relative_path(entry["path"])
            if path not in ALLOWED_TESTS and not path.startswith(ALLOWED_PREFIXES):
                _fail("specialist_path_forbidden")
            if path in seen:
                _fail("duplicate_specialist_path")
            seen.add(path)
    return value


def compose(integration_root, imaging_root, orthopedic_root, destination, *, require_git=True, _manifest_data=None):
    """Preflight the complete copy, then create a fresh disposable output.

    require_git=False is only for connector-exported local source trees. Every
    specialist blob must still match the immutable pin manifest. _manifest_data
    permits tiny synthetic manifests in tests; the CLI never accepts a manifest.
    No source content, absolute filesystem paths or medical URLs enter receipts.
    """
    created = False
    output = None
    try:
        roots = {"integration": _root(integration_root), "imaging": _root(imaging_root),
                 "orthopedic": _root(orthopedic_root)}
        for name in ("imaging", "orthopedic"):
            root = roots[name]
            other = roots["orthopedic" if name == "imaging" else "imaging"]
            if (root == other or root.is_relative_to(other) or other.is_relative_to(root)
                    or roots["integration"] == root or roots["integration"].is_relative_to(root)):
                _fail("input_roots_overlap")
        nested_sources = tuple(root.relative_to(roots["integration"]) for name, root in roots.items()
                               if name != "integration" and root.is_relative_to(roots["integration"]))

        def excluded(relative):
            path = PurePosixPath(relative)
            return _ignored(path) or any(path.is_relative_to(PurePosixPath(prefix.as_posix()))
                                         for prefix in nested_sources)
        output = Path(destination).absolute()
        _no_symlinks(output)
        if output.exists():
            _fail("destination_exists")
        if not output.parent.is_dir():
            _fail("destination_parent_unavailable")
        output = output.parent.resolve(strict=True) / output.name
        if any(output == root or output.is_relative_to(root) for root in roots.values()):
            _fail("destination_inside_source")
        manifest = _manifest(_manifest_data if _manifest_data is not None else
                             json.loads(_read(roots["integration"], MANIFEST_PATH)))
        revisions = {name: item["revision"] for name, item in manifest["producers"].items()}
        integration_revision = None
        if require_git:
            for name, revision in revisions.items():
                if _git(roots[name], "rev-parse", "--verify", "HEAD").decode().strip() != revision:
                    _fail("specialist_revision_changed")
            integration_revision = _git(roots["integration"], "rev-parse", "--verify", "HEAD").decode().strip()
            _git(roots["integration"], "merge-base", "--is-ancestor",
                 manifest["integration_base_revision"], integration_revision)
            names = _git(roots["integration"], "ls-files", "-z", "--cached").decode("utf-8").split("\0")
            integration_paths = sorted(path for path in names if path and not excluded(path))
        else:
            integration_paths = []
            for directory, directories, files in os.walk(roots["integration"], followlinks=False):
                directories[:] = [name for name in directories if not excluded(
                    (Path(directory) / name).relative_to(roots["integration"]).as_posix())]
                for name in directories:
                    _no_symlinks(Path(directory) / name)
                for name in files:
                    path = (Path(directory) / name).relative_to(roots["integration"]).as_posix()
                    if not excluded(path):
                        integration_paths.append(path)
            integration_paths.sort()
        if len(integration_paths) > 10000:
            _fail("composition_size_limit_exceeded")
        planned, total_bytes = {}, 0
        for path in integration_paths:
            data = _read(roots["integration"], path)
            total_bytes += len(data)
            if total_bytes > MAX_TOTAL_BYTES:
                _fail("composition_size_limit_exceeded")
            planned[path] = data
        for path in manifest["protected_integration_paths"]:
            if path not in planned:
                _fail("protected_integration_file_missing")
        specialist_files = []
        for name in sorted(manifest["producers"]):
            for entry in sorted(manifest["producers"][name]["files"], key=lambda item: item["path"]):
                path = entry["path"]
                if path in planned:
                    _fail("specialist_would_overwrite_integration")
                data = _read(roots[name], path)
                if _blob(data) != entry["git_blob_sha1"]:
                    _fail("specialist_blob_changed")
                total_bytes += len(data)
                if total_bytes > MAX_TOTAL_BYTES:
                    _fail("composition_size_limit_exceeded")
                planned[path] = data
                specialist_files.append({"producer": name, "path": path,
                                         "git_blob_sha1": _blob(data), "sha256": hashlib.sha256(data).hexdigest()})
        if len(planned) > 10000 or sum(map(len, planned.values())) > MAX_TOTAL_BYTES:
            _fail("composition_size_limit_exceeded")
        integration_digests = {path: hashlib.sha256(planned[path]).hexdigest() for path in integration_paths}
        receipt = {
            "schema_version": "1.0.0", "manifest_sha256": _digest(manifest),
            "integration_revision": integration_revision,
            "integration_base_revision": manifest["integration_base_revision"],
            "specialist_revisions": revisions,
            "git_revisions_verified": bool(require_git), "specialist_blob_hashes_verified": True,
            "integration_file_count": len(integration_paths), "specialist_file_count": len(specialist_files),
            "integration_tree_sha256": _digest(integration_digests), "specialist_files": specialist_files,
            "protected_integration_sha256s": {path: integration_digests[path]
                                              for path in sorted(manifest["protected_integration_paths"])},
            "synthetic_test_only": True, "is_clinically_validated": False,
            "authorizes_deployment": False, "authorizes_treatment": False,
        }
        output.mkdir(mode=0o700)
        created = True
        for path, data in sorted(planned.items()):
            target = output / path
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as handle:
                handle.write(data)
        return receipt
    except CompositionError:
        if created:
            shutil.rmtree(output, ignore_errors=True)
        raise
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, subprocess.SubprocessError):
        if created:
            shutil.rmtree(output, ignore_errors=True)
        raise CompositionError("composition_input_unavailable") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--integration-root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--imaging-root", required=True)
    parser.add_argument("--orthopedic-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--allow-exported-sources", action="store_true")
    args = parser.parse_args()
    try:
        receipt = compose(args.integration_root, args.imaging_root, args.orthopedic_root, args.output,
                          require_git=not args.allow_exported_sources)
    except CompositionError as error:
        print(json.dumps({"error_code": str(error), "synthetic_test_only": True}))
        return 2
    print(json.dumps(receipt, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
