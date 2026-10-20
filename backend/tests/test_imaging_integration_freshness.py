"""Actual PR44 API freshness, using only the existing in-memory SQLite fixtures."""

from dataclasses import replace

import pytest

pytest.importorskip("backend.app.services.clinical_integration.service")

from backend.app.api.routes.clinical_integration import get_integration_adapters
from backend.app.decision_intelligence import ClinicalInput
from backend.app.imaging_intelligence.integration import GatedImagingRecordAdapter, ReportSeriesBinding
from backend.app.imaging_intelligence.series import SeriesMetadataReader, StudySeriesValidator
from backend.app.main import app
from backend.app.services.clinical_integration.adapters import local_adapters, source_bundle
from backend.app.services.physician_copilot import PhysicianCopilotService
from backend.tests.test_clinical_integration import (
    create_run, enable_preview, inputs, physician, review_body, run_url, visit,
)
from backend.tools.imaging_metadata_demo import SYNTHETIC_REFERENCE_KEY
from backend.tools.imaging_series_demo import generate_synthetic_series


pytestmark = pytest.mark.usefixtures("authenticated_admin")


@pytest.mark.parametrize("dependency", ["study", "clinical", "binding"])
def test_changed_sidecar_invalidates_saved_run_and_blocks_review(
        client, db_session, visit, inputs, physician, tmp_path, dependency):
    fixture = generate_synthetic_series(tmp_path)
    study = StudySeriesValidator(SeriesMetadataReader(reference_key=SYNTHETIC_REFERENCE_KEY)).read(
        fixture.files, expected=(fixture.expected,))
    copilot = PhysicianCopilotService.get_snapshot(db_session, visit["id"])
    context_sha = copilot.manifest.clinical_context_sha256
    bundle = source_bundle(db_session, copilot.clinical_context, context_sha)
    source = next(x.source for x in bundle.core_input.observations if x.observation.category == "imaging")
    values = dict(study=study,
                  binding=ReportSeriesBinding(source.record_id, source.version, source.content_sha256,
                                              context_sha, study.series[0].sha256),
                  clinical=ClinicalInput(("assessment_context", "clinical_review"), "KNEE", "L"))
    adapter = GatedImagingRecordAdapter(**values)
    adapters = local_adapters() | {"imaging": adapter}
    app.dependency_overrides[get_integration_adapters] = lambda: adapters
    response = create_run(client, visit)
    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved["freshness"] == "current"
    assert saved["result"]["workflow_state"] == "awaiting_physician_review"

    if dependency == "study":
        values["study"] = replace(study, status="invalid")
    elif dependency == "clinical":
        values["clinical"] = ClinicalInput()
    else:
        values["binding"] = replace(values["binding"], series_sha256="f"*64)
    adapters["imaging"] = GatedImagingRecordAdapter(**values)
    assert adapters["imaging"].collect(bundle.core_input).status == "unavailable"
    current = client.get(run_url(visit, saved)).json()
    assert current["freshness"] == "stale"
    assert "imaging_component_changed" in current["invalidation_reasons"]
    assert current["result_sha256"] == saved["result_sha256"]
    assert current["result"] == saved["result"]
    assert client.post(run_url(visit, saved) + "/reviews", headers=physician,
                       json=review_body(saved)).status_code == 409
    # A new request evaluates the new dependency state, never reuses the old gate.
    retry = create_run(client, visit, key="after-sidecar-change")
    assert retry.status_code == 201, retry.text
    assert retry.json()["result"]["workflow_state"] == "blocked"
    assert not any(x["core"] == "imaging" for x in retry.json()["result"]["confirmed_findings"])
