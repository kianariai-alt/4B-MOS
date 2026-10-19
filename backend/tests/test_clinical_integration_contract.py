"""Synthetic producer compatibility and explicit safety invariants."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

from pydantic import ValidationError
import pytest

from backend.app.schemas.clinical_integration import CoreOutput, DecisionSupportResult, IntegrationRunCreate
from backend.tools.clinical_integration_demo import synthetic_result


def test_synthetic_two_core_round_trip_and_traceability():
    result = synthetic_result()
    assert DecisionSupportResult.model_validate_json(result.model_dump_json()) == result
    assert [core.core for core in result.cores] == ["orthopedic", "imaging"]
    assert len(result.confirmed_findings) == 2
    assert all(item.approval for item in result.confirmed_findings)
    assert result.unreviewed_findings == ()
    assert result.is_diagnosis is result.is_recommendation is result.authorizes_treatment is False
    assert len(result.provenance.core_output_sha256s) == 2


@pytest.mark.parametrize("field,value", [
    ("contract_version", "2.0.0"), ("patient_name", "Must not be accepted"),
    ("review_status", "approved"), ("is_approved", True),
])
def test_producer_cannot_add_approval_demographics_or_incompatible_version(field, value):
    core = synthetic_result().cores[1].model_dump(mode="json")
    core[field] = value
    with pytest.raises(ValidationError):
        CoreOutput.model_validate(core)


@pytest.mark.parametrize("change", ["duplicate", "nan", "naive_timestamp", "nonmodel_probability", "unavailable_findings"])
def test_invalid_producer_shapes_fail_closed(change):
    core = synthetic_result().cores[1].model_dump(mode="json")
    if change == "duplicate":
        core["findings"].append(deepcopy(core["findings"][0]))
    elif change == "nan":
        core["findings"][0].update(origin="model", confidence=float("nan"))
        core["component"]["kind"] = "model"
    elif change == "naive_timestamp":
        core["generated_at"] = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    elif change == "nonmodel_probability":
        core["findings"][0]["confidence"] = 1
    else:
        core["status"] = "unavailable"
    with pytest.raises(ValidationError):
        CoreOutput.model_validate(core)


def test_request_rejects_client_review_claims_and_duplicate_knowledge():
    with pytest.raises(ValidationError):
        IntegrationRunCreate(request_key="a", expected_clinical_context_sha256="a" * 64,
                             knowledge_fact_ids=("same", "same"))
    with pytest.raises(ValidationError):
        IntegrationRunCreate(request_key="a", expected_clinical_context_sha256="a" * 64,
                             imaging_approved=True)


def test_published_producer_schema_matches_the_current_contract():
    schema = Path(__file__).resolve().parents[2] / "docs/contracts/unified-clinical-core-output-1.0.0.schema.json"
    assert json.loads(schema.read_text(encoding="utf-8")) == CoreOutput.model_json_schema()
