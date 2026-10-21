"""Disposable composition controls using tiny synthetic source bytes only."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from backend.tools.compose_clinical_handoff import CompositionError, compose


def blob(value):
    return hashlib.sha1(b"blob " + str(len(value)).encode() + b"\0" + value).hexdigest()


@pytest.fixture
def sources(tmp_path):
    roots = {name: tmp_path / name for name in ("integration", "imaging", "orthopedic")}
    files = {
        "integration": ("backend/app/services/clinical_integration/engine.py", b"synthetic protected integration\n"),
        "imaging": ("backend/app/imaging_intelligence/models.py", b"synthetic imaging module\n"),
        "orthopedic": ("backend/app/schemas/orthopedic_adapter.py", b"synthetic orthopedic module\n"),
    }
    for name, (relative, value) in files.items():
        path = roots[name] / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    manifest = {
        "manifest_version": "1.0.0", "integration_base_revision": "a" * 40,
        "protected_integration_paths": [files["integration"][0]],
        "producers": {name: {"revision": token * 40,
                             "files": [{"path": files[name][0], "git_blob_sha1": blob(files[name][1])}]}
                      for name, token in (("imaging", "b"), ("orthopedic", "c"))},
    }
    return roots, files, manifest, tmp_path / "output"


def run(sources, **kwargs):
    roots, _, manifest, destination = sources
    return compose(roots["integration"], roots["imaging"], roots["orthopedic"], destination,
                   require_git=False, _manifest_data=manifest, **kwargs)


def test_exact_copy_preserves_protected_core_and_receipt_is_repeatable(sources):
    roots, files, manifest, output = sources
    first = run(sources)
    for name, (path, value) in files.items():
        assert (output / path).read_bytes() == value
        assert (roots[name] / path).read_bytes() == value
    second = compose(roots["integration"], roots["imaging"], roots["orthopedic"], output.with_name("other"),
                     require_git=False, _manifest_data=manifest)
    assert first == second
    assert first["synthetic_test_only"] is True
    assert first["is_clinically_validated"] is first["authorizes_deployment"] is False
    assert first["authorizes_treatment"] is first["git_revisions_verified"] is False
    assert first["integration_revision"] is None
    assert first["integration_base_revision"] == manifest["integration_base_revision"]
    assert first["specialist_blob_hashes_verified"] is True
    assert first["specialist_file_count"] == 2
    text = json.dumps(first)
    assert str(output.parent) not in text
    assert "synthetic protected integration" not in text


def test_tampered_specialist_fails_before_creating_destination(sources):
    roots, files, _, output = sources
    (roots["imaging"] / files["imaging"][0]).write_bytes(b"secret patient content must not leak")
    with pytest.raises(CompositionError, match="^specialist_blob_changed$") as error:
        run(sources)
    assert "patient" not in str(error.value)
    assert not output.exists()


def test_missing_specialist_fails_without_partial_destination(sources):
    roots, files, _, output = sources
    (roots["orthopedic"] / files["orthopedic"][0]).unlink()
    with pytest.raises(CompositionError, match="source_file_unavailable"):
        run(sources)
    assert not output.exists()


def test_specialist_cannot_overwrite_current_integration_file(sources):
    roots, files, _, output = sources
    path = roots["integration"] / files["imaging"][0]
    path.parent.mkdir(parents=True)
    path.write_bytes(b"integration owns this file")
    with pytest.raises(CompositionError, match="specialist_would_overwrite_integration"):
        run(sources)
    assert path.read_bytes() == b"integration owns this file"
    assert not output.exists()


@pytest.mark.parametrize("path", ["../escape.py", "/tmp/absolute.py", "backend/app/services/../core/config.py",
                                 "backend\\app\\services\\escape.py", "backend/app/api/routes/replacement.py",
                                 "backend/migrations/versions/unsafe.py", "backend/app/core/config.py"])
def test_manifest_traversal_and_forbidden_paths_are_rejected(sources, path):
    _, _, manifest, output = sources
    manifest["producers"]["imaging"]["files"][0]["path"] = path
    with pytest.raises(CompositionError):
        run(sources)
    assert not output.exists()


def test_symlinked_specialist_file_is_rejected_even_with_matching_bytes(sources):
    roots, files, _, output = sources
    path = roots["imaging"] / files["imaging"][0]
    outside = output.parent / "outside.txt"
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(CompositionError, match="source_symlink_forbidden"):
        run(sources)
    assert not output.exists()


def test_symlinked_integration_file_is_rejected(sources):
    roots, _, _, output = sources
    outside = output.parent / "outside.txt"
    outside.write_text("never copy an external source")
    (roots["integration"] / "linked.txt").symlink_to(outside)
    with pytest.raises(CompositionError, match="source_symlink_forbidden"):
        run(sources)
    assert not output.exists()


def test_existing_destination_remains_untouched(sources):
    _, _, _, output = sources
    output.mkdir()
    (output / "existing.txt").write_text("preserve")
    with pytest.raises(CompositionError, match="destination_exists"):
        run(sources)
    assert (output / "existing.txt").read_text() == "preserve"


def test_output_inside_an_input_root_is_rejected(sources):
    roots, files, manifest, _ = sources
    output = roots["integration"] / "output"
    with pytest.raises(CompositionError, match="destination_inside_source"):
        run((roots, files, manifest, output))
    assert not output.exists()


def test_default_mode_requires_real_git_revision_verification(sources):
    roots, _, manifest, output = sources
    with pytest.raises(CompositionError, match="git_revision_not_verified"):
        compose(roots["integration"], roots["imaging"], roots["orthopedic"], output, _manifest_data=manifest)
    assert not output.exists()


def commit(root):
    def command(*args):
        return subprocess.run(["git", "-C", str(root), *args], check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode().strip()
    if not (root / ".git").exists():
        command("init", "-q")
    command("add", ".")
    command("-c", "user.name=Synthetic Fixture", "-c", "user.email=fixture@example.test",
            "commit", "-qm", "Synthetic compatibility fixture")
    return command("rev-parse", "HEAD")


def test_verified_git_mode_accepts_integration_descendant_and_exact_specialist_pins(sources):
    roots, _, manifest, output = sources
    manifest["integration_base_revision"] = commit(roots["integration"])
    new_file = roots["integration"] / "new.py"
    new_file.write_text("synthetic followup module\n")
    integration_head = commit(roots["integration"])
    for name in ("imaging", "orthopedic"):
        manifest["producers"][name]["revision"] = commit(roots[name])
    receipt = compose(roots["integration"], roots["imaging"], roots["orthopedic"], output,
                      _manifest_data=manifest)
    assert receipt["git_revisions_verified"] is True
    assert receipt["integration_revision"] == integration_head
    assert (output / "new.py").read_bytes() == new_file.read_bytes()
    assert not (output / ".git").exists()


def test_git_revision_mismatch_is_rejected_before_copy(sources):
    roots, _, manifest, output = sources
    manifest["integration_base_revision"] = commit(roots["integration"])
    for name in ("imaging", "orthopedic"):
        manifest["producers"][name]["revision"] = commit(roots[name])
    (roots["imaging"] / "new.py").write_text("synthetic changed producer\n")
    commit(roots["imaging"])
    with pytest.raises(CompositionError, match="specialist_revision_changed"):
        compose(roots["integration"], roots["imaging"], roots["orthopedic"], output,
                _manifest_data=manifest)
    assert not output.exists()


def test_duplicate_and_missing_protected_paths_fail_closed(sources):
    _, _, manifest, output = sources
    changed = deepcopy(manifest)
    changed["protected_integration_paths"] = ["missing.py"]
    roots = sources[0]
    with pytest.raises(CompositionError, match="protected_integration_file_missing"):
        compose(roots["integration"], roots["imaging"], roots["orthopedic"], output,
                require_git=False, _manifest_data=changed)
    manifest["producers"]["orthopedic"]["files"] = deepcopy(manifest["producers"]["imaging"]["files"])
    with pytest.raises(CompositionError, match="duplicate_specialist_path"):
        run(sources)
    assert not output.exists()


def test_copy_error_removes_its_partial_destination(sources, monkeypatch):
    output = sources[-1]
    original = Path.open
    def failed_copy(path, *args, **kwargs):
        if path.is_relative_to(output):
            raise OSError("secret filesystem details")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", failed_copy)
    with pytest.raises(CompositionError, match="^composition_input_unavailable$"):
        run(sources)
    assert not output.exists()


def test_caches_databases_and_nested_producer_checkout_are_not_copied(sources):
    roots, files, manifest, output = sources
    for relative in ("local.db", ".env", "__pycache__/cache.pyc", ".handoff-sources/untrusted.py"):
        path = roots["integration"] / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("excluded")
    # Actions checkouts may live in the integration workspace. The nested
    # checkout is never recursively copied; only its pinned new module is.
    nested = roots["integration"] / "nested" / "producer"
    nested.mkdir(parents=True)
    relative, value = files["imaging"]
    (nested / relative).parent.mkdir(parents=True)
    (nested / relative).write_bytes(value)
    (nested / "unallowlisted.txt").write_text("do not copy")
    roots["imaging"] = nested
    receipt = run(sources)
    assert receipt["integration_file_count"] == 1
    assert (output / relative).read_bytes() == value
    assert not (output / "nested").exists()
    assert not (output / ".handoff-sources").exists()
    assert not (output / "local.db").exists()
    assert not (output / ".env").exists()
