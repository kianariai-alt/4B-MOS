import hashlib
import json
import subprocess

import pytest

from deploy.install_stage import InstallError, install_stage


@pytest.fixture
def release(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    def git(*args):
        return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
    git("init", "-b", "initial")
    git("config", "user.name", "Installer Test")
    git("config", "user.email", "test@example.invalid")
    file = repo / "sample.txt"
    file.write_text("before\n")
    git("add", "sample.txt")
    git("commit", "-m", "base")
    base = git("rev-parse", "HEAD")
    before_tree = git("rev-parse", "HEAD^{tree}")
    file.write_text("after\n")
    git("add", "sample.txt")
    git("commit", "-m", "target")
    after_tree = git("rev-parse", "HEAD^{tree}")
    patch = subprocess.run(["git", "diff", "--binary", base, "HEAD"], cwd=repo, check=True, capture_output=True).stdout
    (bundle / "01.patch").write_bytes(patch)
    git("switch", "-c", "review/install", base)
    stage = {"number": 1, "patch": "01.patch", "before_tree": before_tree,
             "after_tree": after_tree, "sha256": hashlib.sha256(patch).hexdigest()}
    (bundle / "release-manifest.json").write_text(json.dumps({"stages": [stage]}))
    return repo, bundle, git


def test_stage_check_then_apply_without_committing(release):
    repo, bundle, git = release
    head = git("rev-parse", "HEAD")
    assert "No files changed" in install_stage(repo, bundle, 1)
    assert (repo / "sample.txt").read_text() == "before\n"
    install_stage(repo, bundle, 1, apply=True)
    assert (repo / "sample.txt").read_text() == "after\n"
    assert git("rev-parse", "HEAD") == head
    assert git("diff", "--cached", "--name-only") == "sample.txt"
    with pytest.raises(InstallError, match="uncommitted"):
        install_stage(repo, bundle, 1, apply=True)


@pytest.mark.parametrize("case", ["wrong_stage", "dirty", "main", "wrong_tree", "corrupt_patch", "outside_bundle"])
def test_stage_refuses_unsafe_installation(release, case):
    repo, bundle, git = release
    if case == "dirty":
        (repo / "unrelated.txt").write_text("user work")
    if case == "main":
        git("branch", "-m", "main")
    if case == "wrong_tree":
        (repo / "other.txt").write_text("other chat work")
        git("add", "other.txt")
        git("commit", "-m", "other work")
    if case == "corrupt_patch":
        (bundle / "01.patch").write_text("corrupt")
    if case == "outside_bundle":
        outside = bundle.parent / "outside.patch"
        outside.write_bytes((bundle / "01.patch").read_bytes())
        manifest = json.loads((bundle / "release-manifest.json").read_text())
        manifest["stages"][0]["patch"] = "../outside.patch"
        (bundle / "release-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(InstallError):
        install_stage(repo, bundle, 99 if case == "wrong_stage" else 1, apply=True)
    assert (repo / "sample.txt").read_text() == "before\n"
