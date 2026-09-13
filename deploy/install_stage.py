"""Check or stage one ordered release patch. No commit, push, migration or reset.

Run this file from the extracted release bundle, not from the repository copy.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


class InstallError(Exception):
    pass


def git(repo, *arguments):
    result = subprocess.run(["git", *arguments], cwd=repo, capture_output=True, text=True)
    if result.returncode:
        raise InstallError("Git check failed. No automatic reset or recovery was attempted.")
    return result.stdout.strip()


def check_stage(repo, bundle, stage_number):
    repo, bundle = Path(repo).resolve(strict=True), Path(bundle).resolve(strict=True)
    if Path(git(repo, "rev-parse", "--show-toplevel")).resolve() != repo:
        raise InstallError("Pass the repository root, not a subdirectory.")
    if git(repo, "status", "--porcelain", "--untracked-files=normal"):
        raise InstallError("Repository has uncommitted or untracked changes. Preserve and review them first.")
    branch = git(repo, "symbolic-ref", "--short", "HEAD")
    if not branch.startswith("review/"):
        raise InstallError("Use a separate review/ branch, not an existing working branch.")
    manifest = json.loads((bundle / "release-manifest.json").read_text(encoding="utf-8"))
    stages = [stage for stage in manifest["stages"] if stage["number"] == stage_number]
    if len(stages) != 1:
        raise InstallError("Unknown stage.")
    stage = stages[0]
    if not re.fullmatch(r"[0-9a-f]{40}", stage["before_tree"]):
        raise InstallError("Invalid release manifest.")
    if git(repo, "rev-parse", "HEAD^{tree}") != stage["before_tree"]:
        raise InstallError("This stage does not match the committed project version. Do not force it.")
    patch = (bundle / stage["patch"]).resolve(strict=True)
    if not patch.is_relative_to(bundle):
        raise InstallError("Patch path is outside the release bundle.")
    if hashlib.sha256(patch.read_bytes()).hexdigest() != stage["sha256"]:
        raise InstallError("Patch checksum mismatch. Extract a fresh trusted copy.")
    git(repo, "apply", "--check", "--index", str(patch))
    return repo, patch, stage


def install_stage(repo, bundle, stage_number, apply=False):
    repo, patch, stage = check_stage(repo, bundle, stage_number)
    if not apply:
        return "Checks passed. No files changed."
    git(repo, "apply", "--index", str(patch))
    if git(repo, "write-tree") != stage["after_tree"]:
        raise InstallError("Applied tree differs from the release. Stop and review; no reset was attempted.")
    return "Stage applied and staged. Run tests, review and commit before the next stage. Nothing was pushed or migrated."


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "apply"])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--stage", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        print(install_stage(args.repo, Path(__file__).resolve().parent, args.stage, args.action == "apply"))
        return 0
    except InstallError as error:
        print("STOP: " + str(error))
        return 1
    except (OSError, ValueError, KeyError):
        print("STOP: checks failed. Preserve the repository and send the diagnostic check results for review; do not reset or force the patch.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
