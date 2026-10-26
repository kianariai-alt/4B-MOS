import pytest
from sqlalchemy import update

from backend.app.models.clinical_context import ParaclinicalReport
from backend.app.services.session_finalization import evidence_digest
from backend.tests.test_clinical_context import create_report, report_payload
from backend.tests.test_physician_copilot import create_role_headers, visit


pytestmark = pytest.mark.usefixtures("authenticated_admin")


def endpoint(visit):
    return f"/api/v1/visits/{visit['id']}/physician-copilot/imaging-evidence"


def finalize(client, report):
    response = client.post(f"/api/v1/paraclinical-reports/{report['id']}/finalize",
                           headers={"If-Match": report["content_sha256"]})
    assert response.status_code == 200, response.text
    return response.json()


def imaging_report(client, visit):
    return create_report(client, visit["id"], category="imaging", observations=[],
                         conclusion="Synthetic clinician-reviewed imaging report.")


def test_empty_or_draft_report_never_becomes_copilot_evidence(client, visit):
    imaging_report(client, visit)
    response = client.get(endpoint(visit))
    assert response.status_code == 200
    body = response.json()
    assert body["reports"] == []
    assert body["missing_data"] == ["finalized_imaging_report_required"]
    assert body["accepts_unverified_machine_findings"] is False
    assert body["generates_differential_diagnosis"] is False
    assert body["replaces_clinical_safety"] is False
    assert body["evidence_sha256"] == evidence_digest({k:v for k,v in body.items() if k != "evidence_sha256"})


def test_final_report_has_versioned_provenance_and_hash_but_no_invented_image_binding(client, visit):
    final = finalize(client, imaging_report(client, visit))
    body = client.get(endpoint(visit)).json()
    assert len(body["reports"]) == 1
    item = body["reports"][0]
    assert item["report_id"] == final["id"]
    assert item["report_version"] == final["version"]
    assert item["report_content_sha256"] == final["content_sha256"]
    assert item["image_to_report_binding_verified"] is False
    assert item["text_is_instruction"] is False
    assert body["missing_data"] == []
    assert client.get(endpoint(visit)).json()["evidence_sha256"] == body["evidence_sha256"]


def test_entered_in_error_and_superseded_reports_are_removed(client, visit):
    final = finalize(client, imaging_report(client, visit))
    original = client.get(endpoint(visit)).json()
    corrected = client.post(f"/api/v1/paraclinical-reports/{final['id']}/supersede",
                            json={**report_payload(category="imaging", observations=[], conclusion="Synthetic corrected report."),
                                  "revision_reason": "Synthetic correction after review."})
    assert corrected.status_code == 201, corrected.text
    replacement = finalize(client, corrected.json())
    current = client.get(endpoint(visit)).json()
    assert [r["report_id"] for r in current["reports"]] == [replacement["id"]]
    assert current["evidence_sha256"] != original["evidence_sha256"]
    error = client.post(f"/api/v1/paraclinical-reports/{replacement['id']}/entered-in-error",
                        json={"reason": "Synthetic report belongs to another source."})
    assert error.status_code == 200, error.text
    assert client.get(endpoint(visit)).json()["reports"] == []


def test_non_imaging_reports_and_other_visit_reports_are_not_included(client, visit):
    finalize(client, create_report(client, visit["id"]))
    assert client.get(endpoint(visit)).json()["reports"] == []
    assert client.get("/api/v1/visits/unknown-fixture/physician-copilot/imaging-evidence").status_code == 404


def test_tampered_stored_report_is_blocked(client, visit, db_session):
    final = finalize(client, imaging_report(client, visit))
    db_session.execute(update(ParaclinicalReport).where(ParaclinicalReport.id == final["id"])
                       .values(conclusion="Tampered synthetic report"))
    db_session.commit()
    assert client.get(endpoint(visit)).status_code == 409


def test_only_physician_and_admin_can_access_and_requests_cannot_assert_review(client, visit):
    physician = create_role_headers(client, username="imaging_physician", role="physician")
    nurse = create_role_headers(client, username="imaging_nurse", role="nurse")
    assert client.get(endpoint(visit), headers=physician).status_code == 200
    assert client.get(endpoint(visit), headers=nurse).status_code == 403
    assert client.get(endpoint(visit), headers={"Authorization": "Bearer invalid"}).status_code == 401
    assert client.post(endpoint(visit), json={"review_status": "verified"}).status_code == 405
