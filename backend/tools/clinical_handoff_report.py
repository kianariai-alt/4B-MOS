"""Verify pinned synthetic specialist artifacts without importing medical authority.

Run in the disposable composition produced by compose_clinical_handoff. This
tool emits hashes, counts and compatibility limits, never patient/source text.
It does not register an adapter, access a database, or fetch remote schemas.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat

from pydantic import ValidationError

from backend.app.schemas.clinical_integration import CONTRACT_VERSION, CoreOutput
from backend.app.services.clinical_integration.engine import ENGINE_VERSION
from backend.app.services.session_finalization import evidence_digest

MAX_ARTIFACT_BYTES = 2 * 1024 * 1024


class HandoffVerificationError(Exception):
    """Static error codes only; never expose payloads, source URLs or paths."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise HandoffVerificationError("duplicate_json_key")
        result[key] = value
    return result


def _invalid_number(value):
    raise HandoffVerificationError("nonfinite_json_number")


def _read_bounded(path):
    try:
        if path.is_symlink():
            raise HandoffVerificationError("invalid_artifact_file")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise HandoffVerificationError("invalid_artifact_file")
            value = stream.read(MAX_ARTIFACT_BYTES + 1)
        if len(value) > MAX_ARTIFACT_BYTES:
            raise HandoffVerificationError("invalid_artifact_file")
        return value
    except OSError as error:
        raise HandoffVerificationError("artifact_unreadable") from error


def _decode_json(value):
    try:
        return json.loads(value.decode("utf-8"), object_pairs_hook=_unique_object,
                          parse_constant=_invalid_number)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise HandoffVerificationError("artifact_unreadable") from error


def load_json(path):
    return _decode_json(_read_bounded(path))


def _local_schema_only(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"$ref", "$dynamicRef", "$recursiveRef"} and (
                not isinstance(item, str) or not item.startswith("#")
            ):
                raise HandoffVerificationError("remote_schema_reference_forbidden")
            _local_schema_only(item)
    elif isinstance(value, list):
        for item in value:
            _local_schema_only(item)


def validate_authoring_preview(payload, schema):
    """Use the producer's actual schema, then assert the consumer trust boundary."""
    if not isinstance(payload, dict) or not isinstance(schema, dict):
        raise HandoffVerificationError("orthopedic_producer_schema_invalid")
    try:
        from jsonschema import Draft202012Validator
    except ImportError as error:
        raise HandoffVerificationError("optional_schema_validator_unavailable") from error
    _local_schema_only(schema)
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(payload)
    except Exception as error:
        raise HandoffVerificationError("orthopedic_producer_schema_invalid") from error
    required = {
        "schema_id": "4b-mos.orthopedic-decision-knowledge", "schema_version": "1.0.0",
        "governance_status": "draft", "workflow_state": "preview_only",
        "approved_fact_count": 0, "safety_evaluation": "not_performed",
        "existing_safety_engine_required": True, "requires_independent_review": True,
        "is_diagnosis": False, "is_recommendation": False,
        "is_clinical_clearance": False, "authorizes_treatment": False,
    }
    if any(type(payload.get(key)) is not type(value) or payload.get(key) != value
           for key, value in required.items()):
        raise HandoffVerificationError("orthopedic_authority_claim_rejected")
    if not isinstance(payload.get("evidence_references"), list):
        raise HandoffVerificationError("orthopedic_producer_schema_invalid")
    for item in payload["evidence_references"]:
        if (not isinstance(item, dict) or item.get("governance_status") != "draft"
                or item.get("usable_as_approved_knowledge") is not False
                or "approved_content_sha256" not in item or item["approved_content_sha256"] is not None):
            raise HandoffVerificationError("draft_knowledge_promotion_rejected")
    try:
        expected = evidence_digest({key: value for key, value in payload.items() if key != "result_sha256"})
    except (TypeError, ValueError) as error:
        raise HandoffVerificationError("orthopedic_result_digest_mismatch") from error
    if payload.get("result_sha256") != expected:
        raise HandoffVerificationError("orthopedic_result_digest_mismatch")
    try:
        CoreOutput.model_validate(payload)
    except ValidationError:
        pass
    else:
        raise HandoffVerificationError("authoring_preview_must_not_be_core_output")


def _artifact(root, manifest, producer, path):
    try:
        entries = manifest["producers"][producer]["files"]
        entry = next(item for item in entries if item["path"] == path)
        target = root / path
        if target.is_symlink() or not target.resolve().is_relative_to(root.resolve()):
            raise HandoffVerificationError("invalid_artifact_file")
        value = _read_bounded(target)
        digest = hashlib.sha1(b"blob " + str(len(value)).encode() + b"\0" + value).hexdigest()
        if digest != entry["git_blob_sha1"]:
            raise HandoffVerificationError("producer_artifact_pin_mismatch")
        return _decode_json(value), hashlib.sha256(value).hexdigest()
    except (KeyError, StopIteration, OSError, TypeError) as error:
        raise HandoffVerificationError("producer_artifact_unavailable") from error


def build_report(root: Path):
    manifest = load_json(root / "backend/compatibility/specialist_pins.json")
    image, image_sha = _artifact(root, manifest, "imaging", "docs/examples/imaging-core-v1-synthetic.json")
    if not isinstance(image, dict) or image.get("synthetic_only") is not True:
        raise HandoffVerificationError("synthetic_artifact_required")
    try:
        core = CoreOutput.model_validate(image["core_output"])
    except (KeyError, TypeError, ValidationError) as error:
        raise HandoffVerificationError("imaging_core_contract_invalid") from error
    if core.core != "imaging":
        raise HandoffVerificationError("imaging_core_contract_invalid")
    orthopedic, orthopedic_sha = _artifact(
        root, manifest, "orthopedic", "docs/examples/orthopedic-knee-synthetic-preview.json",
    )
    schema, schema_sha = _artifact(
        root, manifest, "orthopedic", "docs/contracts/orthopedic-decision-knowledge-1.0.0.schema.json",
    )
    validate_authoring_preview(orthopedic, schema)
    report = {
        "schema_version": "1.0.0", "scope": "offline_synthetic_contract_handoff",
        "integration_contract_version": CONTRACT_VERSION, "integration_engine_version": ENGINE_VERSION,
        "integration_contract_sha256": hashlib.sha256(
            (root / "backend/app/schemas/clinical_integration.py").read_bytes(),
        ).hexdigest(),
        "imaging": {
            "producer_revision": manifest["producers"]["imaging"]["revision"],
            "fixture_sha256": image_sha, "core_contract": "accepted",
            "readiness_scope": "data_validation_only", "source_review_authority": "not_provided_by_adapter",
            "fixture_freshness": "historical_fixture_only", "finding_count": len(core.findings),
            "clinical_clearance": False,
        },
        "orthopedic": {
            "producer_revision": manifest["producers"]["orthopedic"]["revision"],
            "fixture_sha256": orthopedic_sha, "schema_sha256": schema_sha,
            "producer_result_sha256": orthopedic["result_sha256"],
            "producer_context_sha256": orthopedic["context_sha256"],
            "clinical_context_binding": "not_established", "core_contract": "incompatible_authoring_preview",
            "disposition": "draft_quarantined", "approved_fact_count": 0,
            "draft_evidence_count": len(orthopedic["evidence_references"]),
            "question_count": len(orthopedic["question_candidates"]),
            "finding_review_authority": "not_authenticated_by_answer_state",
            "safety_evaluation": "not_performed",
        },
        "specialist_code_activated_in_api": False, "is_clinical_validation": False,
        "is_diagnosis": False, "authorizes_treatment": False, "is_clinical_clearance": False,
    }
    return {**report, "receipt_sha256": evidence_digest(report)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    try:
        report = build_report(args.root.resolve())
    except (HandoffVerificationError, OSError, ValueError) as error:
        code = str(error) if isinstance(error, HandoffVerificationError) else "handoff_verification_failed"
        print(json.dumps({"status": "failed", "code": code}))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
