"""Unit tests for the offline consumer boundary, using fabricated metadata only.

The schema-validator fixture is deliberately a no-op: these cases test the
consumer's independent guards, not producer JSON Schema correctness. Actual
producer validation is exercised with real jsonschema in compatibility CI.
"""

from copy import deepcopy
import builtins
import hashlib
import json
import os
from pathlib import Path
import sys
import types

import pytest

from backend.app.services.session_finalization import evidence_digest
from backend.tools import clinical_handoff_report as report


@pytest.fixture
def schema_validator(monkeypatch):
    calls = []
    module = types.ModuleType("jsonschema")
    exceptions = types.ModuleType("jsonschema.exceptions")
    class SchemaError(Exception):
        pass
    class SchemaValidationError(Exception):
        pass
    class Validator:
        @staticmethod
        def check_schema(schema):
            calls.append("check_schema")
        def __init__(self, schema):
            calls.append("construct")
        def validate(self, payload):
            calls.append("validate")
    module.Draft202012Validator = Validator
    exceptions.SchemaError = SchemaError
    exceptions.ValidationError = SchemaValidationError
    monkeypatch.setitem(sys.modules, "jsonschema", module)
    monkeypatch.setitem(sys.modules, "jsonschema.exceptions", exceptions)
    return calls


def preview(**changes):
    value = {
        "schema_id": "4b-mos.orthopedic-decision-knowledge", "schema_version": "1.0.0",
        "governance_status": "draft", "workflow_state": "preview_only",
        "approved_fact_count": 0, "safety_evaluation": "not_performed",
        "existing_safety_engine_required": True, "requires_independent_review": True,
        "is_diagnosis": False, "is_recommendation": False,
        "is_clinical_clearance": False, "authorizes_treatment": False,
        "evidence_references": [], "question_candidates": [],
        "context_sha256": "a" * 64,
    }
    value.update(changes)
    value["result_sha256"] = evidence_digest(value)
    return value


def assert_static_error(code, operation):
    with pytest.raises(report.HandoffVerificationError) as error:
        operation()
    assert str(error.value) == code
    assert all(text not in str(error.value) for text in ["private", "token=", "https://", "Sensitive"])


def test_consumer_accepts_fabricated_draft_without_promoting_it(schema_validator):
    payload = preview()
    original = deepcopy(payload)
    report.validate_authoring_preview(payload, {"type": "object"})
    assert payload == original
    assert schema_validator == ["check_schema", "construct", "validate"]


@pytest.mark.parametrize("data", [
    '{"flag":false,"flag":true}',
    '{"nested":{"result":1,"result":2}}',
])
def test_duplicate_keys_fail_before_any_semantic_interpretation(tmp_path, data):
    path = tmp_path / "synthetic.json"
    path.write_text(data)
    assert_static_error("duplicate_json_key", lambda: report.load_json(path))


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_json_is_never_accepted(tmp_path, constant):
    path = tmp_path / "synthetic.json"
    path.write_text('{"nested":{"value":' + constant + '}}')
    assert_static_error("nonfinite_json_number", lambda: report.load_json(path))


@pytest.mark.parametrize("data", [b"\xff\xfe", b'{"private-token":"unterminated'])
def test_malformed_text_has_static_errors_without_source_content(tmp_path, data):
    path = tmp_path / "private-input.json"
    path.write_bytes(data)
    assert_static_error("artifact_unreadable", lambda: report.load_json(path))


def test_missing_artifact_has_no_path_in_error(tmp_path):
    assert_static_error("artifact_unreadable", lambda: report.load_json(tmp_path / "private-path.json"))


def test_file_bound_rejects_large_artifacts_and_symlinks(tmp_path):
    path = tmp_path / "synthetic.json"
    path.write_bytes(b" " * (report.MAX_ARTIFACT_BYTES + 1))
    assert_static_error("invalid_artifact_file", lambda: report.load_json(path))
    safe = tmp_path / "source.json"
    safe.write_text("{}")
    link = tmp_path / "link.json"
    link.symlink_to(safe)
    assert_static_error("invalid_artifact_file", lambda: report.load_json(link))


def test_file_bound_holds_when_file_grew_after_size_metadata(tmp_path, monkeypatch):
    path = tmp_path / "synthetic.json"
    path.write_bytes(b" " * (report.MAX_ARTIFACT_BYTES + 1))
    original = Path.stat
    def smaller_metadata(current, *args, **kwargs):
        result = original(current, *args, **kwargs)
        if current == path:
            fields = list(result)
            fields[6] = 2
            return os.stat_result(fields)
        return result
    monkeypatch.setattr(Path, "stat", smaller_metadata)
    assert_static_error("invalid_artifact_file", lambda: report.load_json(path))


@pytest.mark.parametrize("keyword", ["$ref", "$dynamicRef", "$recursiveRef"])
@pytest.mark.parametrize("target", ["https://private.example/schema?token=Sensitive", "file:///private/schema.json", "relative.json"])
def test_all_nonlocal_schema_references_are_rejected_without_resolving(schema_validator, keyword, target):
    schema = {"type": "object", "$defs": {"nested": {keyword: target}}}
    assert_static_error("remote_schema_reference_forbidden",
                        lambda: report.validate_authoring_preview(preview(), schema))
    assert schema_validator == []


def test_local_schema_fragments_do_not_create_a_network_dependency(schema_validator):
    report.validate_authoring_preview(preview(), {"type": "object", "$ref": "#/$defs/local", "$defs": {"local": {}}})
    assert "validate" in schema_validator


@pytest.mark.parametrize("field,value", [
    ("approved_fact_count", 1), ("approved_fact_count", False),
    ("governance_status", "approved"), ("workflow_state", "ready"),
    ("existing_safety_engine_required", False), ("requires_independent_review", False),
    ("safety_evaluation", "no_alerts"), ("authorizes_treatment", True),
    ("is_diagnosis", True), ("is_recommendation", True), ("is_clinical_clearance", True),
    ("is_clinical_clearance", 0),
])
def test_consumer_rejects_authority_even_if_schema_accepts_it(schema_validator, field, value):
    payload = preview(**{field: value})
    assert_static_error("orthopedic_authority_claim_rejected",
                        lambda: report.validate_authoring_preview(payload, {"type": "object"}))


@pytest.mark.parametrize("reference", [
    {"governance_status": "approved", "usable_as_approved_knowledge": False, "approved_content_sha256": None},
    {"governance_status": "draft", "usable_as_approved_knowledge": True, "approved_content_sha256": None},
    {"governance_status": "draft", "usable_as_approved_knowledge": False, "approved_content_sha256": "a" * 64},
])
def test_consumer_rejects_draft_promotion_independently(schema_validator, reference):
    payload = preview(evidence_references=[reference])
    assert_static_error("draft_knowledge_promotion_rejected",
                        lambda: report.validate_authoring_preview(payload, {"type": "object"}))


def test_digest_mismatch_is_static_and_rejects_otherwise_valid_preview(schema_validator):
    payload = preview()
    payload["result_sha256"] = "0" * 64
    assert_static_error("orthopedic_result_digest_mismatch",
                        lambda: report.validate_authoring_preview(payload, {"type": "object"}))


@pytest.mark.parametrize("payload", [None, [], "private Sensitive input"])
def test_nonobject_payload_has_a_controlled_error(schema_validator, payload):
    assert_static_error("orthopedic_producer_schema_invalid",
                        lambda: report.validate_authoring_preview(payload, {"type": "object"}))


@pytest.mark.parametrize("schema", [None, [], "private Sensitive schema"])
def test_nonobject_schema_has_a_controlled_error(schema_validator, schema):
    assert_static_error("orthopedic_producer_schema_invalid",
                        lambda: report.validate_authoring_preview(preview(), schema))


def test_missing_optional_validator_is_reported_without_fallback(monkeypatch):
    original = builtins.__import__
    def unavailable(name, *args, **kwargs):
        if name == "jsonschema":
            raise ImportError("private Sensitive package path")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", unavailable)
    assert_static_error("optional_schema_validator_unavailable",
                        lambda: report.validate_authoring_preview(preview(), {"type": "object"}))


def test_pinned_artifact_digest_mismatch_is_not_treated_as_valid_json(tmp_path):
    path = tmp_path / "synthetic.json"
    path.write_text("{}")
    manifest = {"producers": {"imaging": {"files": [{"path": path.name, "git_blob_sha1": "0" * 40}]}}}
    assert_static_error("producer_artifact_pin_mismatch", lambda: report._artifact(tmp_path, manifest, "imaging", path.name))


def test_correctly_pinned_artifact_returns_actual_content_and_sha256(tmp_path):
    path = tmp_path / "synthetic.json"
    value = b'{"synthetic_only":true}\n'
    path.write_bytes(value)
    git_digest = hashlib.sha1(b"blob " + str(len(value)).encode() + b"\0" + value).hexdigest()
    manifest = {"producers": {"imaging": {"files": [{"path": path.name, "git_blob_sha1": git_digest}]}}}
    parsed, digest = report._artifact(tmp_path, manifest, "imaging", path.name)
    assert parsed == {"synthetic_only": True}
    assert digest == hashlib.sha256(value).hexdigest()


def test_artifact_bound_applies_before_loading_and_hashing(tmp_path):
    path = tmp_path / "synthetic.json"
    value = b" " * (report.MAX_ARTIFACT_BYTES + 1)
    path.write_bytes(value)
    manifest = {"producers": {"imaging": {"files": [{"path": path.name, "git_blob_sha1": "0" * 40}]}}}
    assert_static_error("invalid_artifact_file", lambda: report._artifact(tmp_path, manifest, "imaging", path.name))
