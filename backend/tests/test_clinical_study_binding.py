"""Synthetic study associations and authenticated review; in-memory SQLite only."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest
from sqlalchemy import event, select, update

from backend.app.core.config import settings
from backend.app.models.audit_log import AuditLog
from backend.app.models.clinical_study_binding import ClinicalStudyBinding, ClinicalStudyBindingReview
from backend.tests.test_clinical_integration import (
    enable_preview, physician, visit, inputs, add_report, evaluate, create_run, run_url, review_body,
)
from backend.tests.test_physician_copilot import create_role_headers

pytestmark = pytest.mark.usefixtures("authenticated_admin")


def bindings_url(visit):
    return f"/api/v1/visits/{visit['id']}/imaging-study-bindings"


def intelligence_url(visit):
    return f"/api/v1/visits/{visit['id']}/clinical-intelligence"


def binding_body(client, visit, report, *, key="binding-one", previous=None, **changes):
    now = datetime.now(timezone.utc)
    context = client.get(f"/api/v1/visits/{visit['id']}/physician-copilot")
    assert context.status_code == 200, context.text
    return {
        "request_key": key,
        "report_id": report["id"], "report_version": report["version"],
        "report_content_sha256": report["content_sha256"],
        "clinical_context_sha256": context.json()["manifest"]["clinical_context_sha256"],
        "expected_previous_binding_sha256": previous,
        "opaque_study_reference": "11111111-1111-4111-8111-111111111111",
        "opaque_series_reference": "22222222-2222-4222-8222-222222222222",
        "study_sha256": "a" * 64, "series_sha256": "b" * 64,
        "quality_assessment_sha256": "c" * 64, "modality": "MR",
        "imaging_component": {"component_id": "synthetic-imaging-ingress", "version": "1.0.0",
                              "artifact_sha256": "d" * 64, "kind": "adapter"},
        "quality_component": {"component_id": "synthetic-quality-rule", "version": "1.0.0",
                              "artifact_sha256": "e" * 64, "kind": "rule"},
        "quality_status": "data_ready", "source_generated_at": now.isoformat(),
        "source_valid_until": (now + timedelta(hours=1)).isoformat(),
        **changes,
    }


def propose(client, visit, report, **changes):
    response = client.post(bindings_url(visit), json=binding_body(client, visit, report, **changes))
    assert response.status_code == 201, response.text
    return response.json()


def inventory(client, visit):
    response = client.get(bindings_url(visit))
    assert response.status_code == 200, response.text
    return response.json()


def current(client, visit, binding_id):
    return next(item for item in inventory(client, visit)["bindings"] if item["binding"]["id"] == binding_id)


def review_payload(binding, *, action="confirm", key="binding-review-one", previous=None, **changes):
    return {
        "request_key": key, "expected_binding_sha256": binding["binding_sha256"],
        "expected_previous_review_sha256": previous, "action": action,
        "rationale": "Synthetic study association independently reviewed by physician.",
        **changes,
    }


def review(client, visit, binding, physician, **changes):
    return client.post(bindings_url(visit) + f"/{binding['binding']['id']}/reviews",
                       headers=physician, json=review_payload(binding, **changes))


def test_empty_inventory_and_both_gets_are_stable_without_database_writes(client, visit, inputs, db_session):
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.lstrip().split()[0].upper())

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        first, repeated = client.get(bindings_url(visit)), client.get(bindings_url(visit))
        snapshot, again = client.get(intelligence_url(visit)), client.get(intelligence_url(visit))
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert first.status_code == repeated.status_code == snapshot.status_code == again.status_code == 200
    assert first.json() == repeated.json()
    assert first.json()["bindings"] == []
    assert first.headers["Cache-Control"] == snapshot.headers["Cache-Control"] == "no-store"
    assert snapshot.json()["study_bindings"] == first.json()
    assert snapshot.json()["provenance_manifest"]["study_bindings_sha256"] == first.json()["sha256"]
    assert snapshot.json()["snapshot_sha256"] == again.json()["snapshot_sha256"]
    assert not set(statements) & {"INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER"}
    assert db_session.scalar(select(ClinicalStudyBinding)) is None


def test_proposal_and_physician_confirmation_preserve_evidence_and_are_idempotent(
    client, visit, inputs, physician, db_session,
):
    body = binding_body(client, visit, inputs["report"])
    created = client.post(bindings_url(visit), json=body)
    assert created.status_code == 201, created.text
    binding = created.json()
    assert binding["review_status"] == "unverified"
    assert binding["eligible_for_contextual_link"] is False
    assert binding["latest_review_sha256"] is None
    assert binding["binding"]["revision"] == 1
    assert binding["binding"]["previous_binding_sha256"] is None
    assert client.post(bindings_url(visit), json=body).json() == binding
    assert client.post(bindings_url(visit), json=body | {"study_sha256": "f" * 64}).status_code == 409
    assert client.post(bindings_url(visit), headers=physician, json=body).status_code == 409
    stored = db_session.get(ClinicalStudyBinding, binding["binding"]["id"])
    payload_before = deepcopy(stored.payload)
    inventory_before = inventory(client, visit)
    reviewed = review(client, visit, binding, physician)
    assert reviewed.status_code == 201, reviewed.text
    assert reviewed.json()["action"] == "confirm"
    assert reviewed.json()["verifies_model_findings"] is False
    assert reviewed.json()["dicom_identity_verified"] is False
    assert review(client, visit, binding, physician).json() == reviewed.json()
    updated = current(client, visit, stored.id)
    assert updated["review_status"] == "verified"
    assert updated["freshness"] == "current"
    assert updated["eligible_for_contextual_link"] is True
    assert updated["latest_review_sha256"]
    assert updated["reviews"] == [reviewed.json()]
    assert updated["review_scope"] == "study_to_visit_association"
    assert updated["quality_assertion_verified"] is updated["dicom_identity_verified"] is False
    assert inventory(client, visit)["sha256"] != inventory_before["sha256"]
    db_session.expire_all()
    assert db_session.get(ClinicalStudyBinding, stored.id).payload == payload_before
    rows = db_session.scalars(select(AuditLog).where(AuditLog.entity_id == stored.id)).all()
    assert len(rows) == 2
    audit_data = json.dumps([row.event_data for row in rows])
    assert all(value not in audit_data for value in ["Synthetic", "rationale", "token=", body["opaque_study_reference"]])
    # A clinical snapshot cannot outlive the study metadata it relies on.
    source_expiry = datetime.fromisoformat(binding["binding"]["source_valid_until"].replace("Z", "+00:00"))
    live = client.get(intelligence_url(visit))
    assert live.status_code == 200, live.text
    saved = create_run(client, visit, key="binding-limited-validity")
    assert saved.status_code == 201, saved.text
    for result in (live.json()["result"], saved.json()["result"]):
        assert datetime.fromisoformat(result["valid_until"].replace("Z", "+00:00")) <= source_expiry


def test_review_cas_and_verified_binding_only_allows_invalidation(client, visit, inputs, physician):
    binding = propose(client, visit, inputs["report"])
    assert review(client, visit, binding, physician, expected_binding_sha256="0" * 64).status_code == 409
    assert review(client, visit, binding, physician, previous="0" * 64).status_code == 409
    confirmed = review(client, visit, binding, physician)
    assert confirmed.status_code == 201, confirmed.text
    latest = current(client, visit, binding["binding"]["id"])
    assert review(client, visit, binding, physician, key="duplicate-confirm",
                  previous=latest["latest_review_sha256"]).status_code == 409
    assert review(client, visit, binding, physician, action="reject", key="reject-confirmed",
                  previous=latest["latest_review_sha256"]).status_code == 409
    assert review(client, visit, binding, physician, action="invalidate", key="wrong-cas").status_code == 409
    invalidated = review(client, visit, binding, physician, action="invalidate", key="invalidate-one",
                         previous=latest["latest_review_sha256"])
    assert invalidated.status_code == 201, invalidated.text
    terminal = current(client, visit, binding["binding"]["id"])
    assert terminal["review_status"] == "invalid"
    assert terminal["eligible_for_contextual_link"] is False
    assert len(terminal["reviews"]) == 2
    assert terminal["reviews"][1]["previous_review_sha256"] == latest["latest_review_sha256"]
    assert review(client, visit, binding, physician, key="resurrect",
                  previous=terminal["latest_review_sha256"]).status_code == 409


@pytest.mark.parametrize("action,status", [("reject", "rejected"), ("invalidate", "invalid")])
def test_terminal_review_requires_new_binding_revision(client, visit, inputs, physician, action, status):
    binding = propose(client, visit, inputs["report"])
    result = review(client, visit, binding, physician, action=action)
    assert result.status_code == 201, result.text
    terminal = current(client, visit, binding["binding"]["id"])
    assert terminal["review_status"] == status
    assert review(client, visit, binding, physician, key="reconfirm",
                  previous=terminal["latest_review_sha256"]).status_code == 409
    replacement = propose(client, visit, inputs["report"], key="replacement", previous=binding["binding_sha256"])
    assert replacement["binding"]["revision"] == 2
    assert replacement["review_status"] == "unverified"
    assert inventory(client, visit)["bindings"] == [replacement]


def test_latest_pending_revision_replaces_prior_verified_link_and_requires_cas(client, visit, inputs, physician):
    first = propose(client, visit, inputs["report"])
    assert review(client, visit, first, physician).status_code == 201
    initial_hash = client.get(intelligence_url(visit)).json()["snapshot_sha256"]
    saved = create_run(client, visit, key="before-model-binding-revision").json()
    no_previous = binding_body(client, visit, inputs["report"], key="without-cas")
    assert client.post(bindings_url(visit), json=no_previous).status_code == 409
    assert client.post(bindings_url(visit), json=no_previous | {
        "expected_previous_binding_sha256": "0" * 64,
    }).status_code == 409
    next_component = dict(no_previous["imaging_component"], version="2.0.0")
    replacement = propose(client, visit, inputs["report"], key="model-revision",
                          previous=first["binding_sha256"], imaging_component=next_component)
    assert replacement["binding"]["previous_binding_sha256"] == first["binding_sha256"]
    assert replacement["binding"]["revision"] == 2
    assert replacement["eligible_for_contextual_link"] is False
    latest = inventory(client, visit)
    assert len(latest["bindings"]) == 1
    assert latest["bindings"][0]["binding"]["id"] == replacement["binding"]["id"]
    response = client.get(intelligence_url(visit))
    assert response.status_code == 200, response.text
    assert response.json()["snapshot_sha256"] != initial_hash
    assert response.json()["result"]["workflow_state"] == "blocked"
    saved_read = client.get(run_url(visit, saved))
    assert saved_read.status_code == 200, saved_read.text
    assert saved_read.json()["freshness"] == "stale"
    assert "study_bindings_changed" in saved_read.json()["invalidation_reasons"]
    historical = client.get(bindings_url(visit) + f"/{first['binding']['id']}")
    assert historical.status_code == 200, historical.text
    assert historical.json()["freshness"] == "stale"
    assert "study_binding_superseded" in historical.json()["invalidation_reasons"]
    assert historical.json()["eligible_for_contextual_link"] is False


@pytest.mark.parametrize("field,value", [
    ("report_version", 999), ("report_content_sha256", "0" * 64),
    ("clinical_context_sha256", "0" * 64),
])
def test_proposal_rejects_changed_source_or_context(client, visit, inputs, field, value):
    body = binding_body(client, visit, inputs["report"], **{field: value})
    response = client.post(bindings_url(visit), json=body)
    assert response.status_code == 409, response.text
    assert inventory(client, visit)["bindings"] == []


def test_cross_visit_and_nonimaging_sources_cannot_be_bound(client, visit, inputs, physician):
    other = client.post(f"/api/v1/patients/{visit['patient_id']}/visits", json={"body_region": "knee"})
    assert other.status_code == 201, other.text
    other_visit = other.json()
    body = binding_body(client, other_visit, inputs["report"])
    assert client.post(bindings_url(other_visit), json=body).status_code == 409
    clinical = add_report(client, visit, physician, key="NOT-IMAGING", imaging=False)
    body = binding_body(client, visit, clinical)
    assert client.post(bindings_url(visit), json=body).status_code == 409
    binding = propose(client, visit, inputs["report"])
    assert review(client, other_visit, binding, physician).status_code == 404
    assert inventory(client, other_visit)["bindings"] == []


@pytest.mark.parametrize("source_state", ["draft", "admin_finalized"])
def test_nonphysician_finalized_source_stays_unverified_and_cannot_confirm(
    client, visit, inputs, physician, source_state,
):
    report = add_report(client, visit, physician, key="UNREVIEWED-IMAGE", finalize=False)
    if source_state == "admin_finalized":
        assert client.post(f"/api/v1/paraclinical-reports/{report['id']}/finalize").status_code == 200
    binding = propose(client, visit, report)
    assert binding["review_status"] == "unverified"
    assert binding["eligible_for_contextual_link"] is False
    assert review(client, visit, binding, physician).status_code == 409


@pytest.mark.parametrize("quality_status", ["blocked", "not_assessed"])
def test_quality_limitations_block_association_confirmation(client, visit, inputs, physician, quality_status):
    binding = propose(client, visit, inputs["report"], quality_status=quality_status)
    assert binding["eligible_for_contextual_link"] is False
    assert review(client, visit, binding, physician).status_code == 409
    response = client.get(intelligence_url(visit))
    assert response.status_code == 200, response.text
    assert response.json()["result"]["workflow_state"] == "blocked"


def test_confirmation_cannot_be_recorded_after_its_source_expires(client, visit, inputs, physician, monkeypatch):
    from backend.app.services import clinical_study_binding as service
    binding = propose(client, visit, inputs["report"])
    observed = service.utcnow()
    times = iter([observed, observed, observed + timedelta(hours=2)])
    monkeypatch.setattr(service, "utcnow", lambda: next(times))
    assert review(client, visit, binding, physician).status_code == 409


@pytest.mark.parametrize("time_case", ["expired", "future", "ancient"])
def test_proposal_rejects_untrustworthy_source_timestamps(client, visit, inputs, time_case):
    now = datetime.now(timezone.utc)
    if time_case == "expired":
        generated, expires = now - timedelta(hours=2), now - timedelta(hours=1)
    elif time_case == "future":
        generated, expires = now + timedelta(hours=1), now + timedelta(hours=2)
    else:
        generated, expires = now - timedelta(days=2), now + timedelta(hours=1)
    body = binding_body(client, visit, inputs["report"], source_generated_at=generated.isoformat(),
                        source_valid_until=expires.isoformat())
    response = client.post(bindings_url(visit), json=body)
    # A validity duration beyond the contract maximum may fail shape validation
    # before the service's freshness guard; either route must reject the source.
    assert response.status_code in {409, 422}, response.text


def test_expiry_and_context_changes_invalidate_links_and_block_new_confirmation(
    client, visit, inputs, physician, monkeypatch,
):
    from backend.app.services import clinical_study_binding as service
    binding = propose(client, visit, inputs["report"])
    initial = client.get(intelligence_url(visit)).json()
    original_now = service.utcnow
    monkeypatch.setattr(service, "utcnow", lambda: original_now() + timedelta(hours=2))
    stale = current(client, visit, binding["binding"]["id"])
    assert stale["freshness"] == "stale"
    assert stale["eligible_for_contextual_link"] is False
    assert review(client, visit, binding, physician).status_code == 409
    monkeypatch.setattr(service, "utcnow", original_now)
    add_report(client, visit, physician, key="CONTEXT-CHANGE", imaging=False)
    changed = current(client, visit, binding["binding"]["id"])
    assert changed["freshness"] == "stale"
    assert review(client, visit, binding, physician).status_code == 409
    response = client.get(intelligence_url(visit))
    assert response.status_code == 200, response.text
    assert response.json()["snapshot_sha256"] != initial["snapshot_sha256"]


def test_binding_and_review_changes_invalidate_saved_runs_and_snapshot_hash(client, visit, inputs, physician):
    run = create_run(client, visit, knowledge=(inputs["fact"]["id"],)).json()
    before = client.get(intelligence_url(visit)).json()
    binding = propose(client, visit, inputs["report"])
    after_proposal = client.get(intelligence_url(visit)).json()
    assert before["snapshot_sha256"] != after_proposal["snapshot_sha256"]
    read = client.get(run_url(visit, run))
    assert read.status_code == 200, read.text
    assert read.json()["freshness"] == "stale"
    assert "study_bindings_changed" in read.json()["invalidation_reasons"]
    assert client.post(run_url(visit, run) + "/reviews", headers=physician,
                       json=review_body(run)).status_code == 409
    assert review(client, visit, binding, physician).status_code == 201
    after_review = client.get(intelligence_url(visit)).json()
    assert after_review["snapshot_sha256"] != after_proposal["snapshot_sha256"]
    assert after_review["provenance_manifest"]["study_bindings_sha256"] == inventory(client, visit)["sha256"]
    manifest = json.dumps(after_review["provenance_manifest"])
    assert all(text not in manifest for text in ["patient_id", "visit_id", "Synthetic", "rationale", "https://", "token="])


def test_binding_and_review_records_are_append_only_and_corruption_fails_closed(
    client, visit, inputs, physician, db_session,
):
    binding = propose(client, visit, inputs["report"])
    record = db_session.get(ClinicalStudyBinding, binding["binding"]["id"])
    record.sha256 = "0" * 64
    with pytest.raises(ValueError, match="append-only"):
        db_session.commit()
    db_session.rollback()
    record = db_session.get(ClinicalStudyBinding, binding["binding"]["id"])
    db_session.delete(record)
    with pytest.raises(ValueError, match="append-only"):
        db_session.commit()
    db_session.rollback()
    reviewed = review(client, visit, binding, physician)
    assert reviewed.status_code == 201, reviewed.text
    row = db_session.get(ClinicalStudyBindingReview, reviewed.json()["id"])
    db_session.delete(row)
    with pytest.raises(ValueError, match="append-only"):
        db_session.commit()
    db_session.rollback()
    # Privileged SQL deliberately bypasses ORM guards to exercise read-time checks.
    row = db_session.get(ClinicalStudyBindingReview, reviewed.json()["id"])
    forged = deepcopy(row.payload)
    forged["action"] = "reject"
    db_session.execute(update(ClinicalStudyBindingReview).where(ClinicalStudyBindingReview.id == row.id)
                       .values(payload=forged))
    db_session.commit()
    response = client.get(bindings_url(visit))
    assert response.status_code == 409, response.text
    assert client.get(intelligence_url(visit)).status_code == 409


def test_corrupt_binding_provenance_is_not_reported_as_success(client, visit, inputs, db_session):
    binding = propose(client, visit, inputs["report"])
    db_session.execute(update(ClinicalStudyBinding).where(ClinicalStudyBinding.id == binding["binding"]["id"])
                       .values(sha256="0" * 64))
    db_session.commit()
    response = client.get(bindings_url(visit))
    assert response.status_code == 409
    assert "Synthetic" not in response.text
    assert client.get(intelligence_url(visit)).status_code == 409


@pytest.mark.parametrize("operation", ["proposal", "review"])
def test_audit_failure_rolls_back_binding_or_review_atomically(
    client, visit, inputs, physician, db_session, monkeypatch, operation,
):
    from backend.app.repositories.audit_log import AuditLogRepository
    binding = propose(client, visit, inputs["report"]) if operation == "review" else None
    audits_before = len(db_session.scalars(select(AuditLog)).all())

    def unavailable(*args, **kwargs):
        raise RuntimeError("Synthetic binding audit unavailable")

    monkeypatch.setattr(AuditLogRepository, "create", unavailable)
    with pytest.raises(RuntimeError, match="binding audit unavailable"):
        if operation == "proposal":
            propose(client, visit, inputs["report"])
        else:
            review(client, visit, binding, physician)
    assert len(db_session.scalars(select(AuditLog)).all()) == audits_before
    assert db_session.scalar(select(ClinicalStudyBindingReview)) is None
    if operation == "proposal":
        assert db_session.scalar(select(ClinicalStudyBinding)) is None
    else:
        assert current(client, visit, binding["binding"]["id"])["review_status"] == "unverified"


@pytest.mark.parametrize("role", ["nurse", "operator", "viewer"])
def test_binding_routes_reject_nonclinical_roles(client, visit, inputs, physician, role):
    binding = propose(client, visit, inputs["report"])
    headers = create_role_headers(client, username=f"study_binding_{role}", role=role)
    body = binding_body(client, visit, inputs["report"], key="unauthorized-proposal",
                        previous=binding["binding_sha256"])
    assert client.get(bindings_url(visit), headers=headers).status_code == 403
    assert client.post(bindings_url(visit), headers=headers, json=body).status_code == 403
    assert client.post(bindings_url(visit) + f"/{binding['binding']['id']}/reviews", headers=headers,
                       json=review_payload(binding)).status_code == 403


def test_admin_cannot_confirm_and_disabled_or_unauthenticated_access_is_rejected(
    client, visit, inputs, physician, monkeypatch,
):
    binding = propose(client, visit, inputs["report"])
    review_url = bindings_url(visit) + f"/{binding['binding']['id']}/reviews"
    assert client.post(review_url, json=review_payload(binding)).status_code == 403
    monkeypatch.setattr(settings, "CLINICAL_INTEGRATION_ENABLED", False)
    assert client.get(bindings_url(visit)).status_code == 404
    assert client.post(bindings_url(visit), json=binding_body(client, visit, inputs["report"])).status_code == 404
    assert client.post(review_url, headers=physician, json=review_payload(binding)).status_code == 404
    monkeypatch.setattr(settings, "CLINICAL_INTEGRATION_ENABLED", True)
    body = binding_body(client, visit, inputs["report"])
    client.headers.clear()
    assert client.get(bindings_url(visit)).status_code == 401
    assert client.post(bindings_url(visit), json=body).status_code == 401
    assert client.post(review_url, json=review_payload(binding)).status_code == 401


@pytest.mark.parametrize("field,value", [
    ("review_status", "verified"), ("dicom_identity_verified", True),
    ("patient_name", "Synthetic forbidden identity"),
    ("image_url", "https://example.test/synthetic?token=never-allowed"),
])
def test_producer_cannot_attach_review_claims_or_identifying_transport_fields(client, visit, inputs, field, value):
    body = binding_body(client, visit, inputs["report"], **{field: value})
    assert client.post(bindings_url(visit), json=body).status_code == 422
    assert inventory(client, visit)["bindings"] == []


def test_physician_can_propose_but_review_claims_cannot_be_injected_into_review(client, visit, inputs, physician):
    body = binding_body(client, visit, inputs["report"])
    proposed = client.post(bindings_url(visit), json=body, headers=physician)
    assert proposed.status_code == 201, proposed.text
    binding = proposed.json()
    assert review(client, visit, binding, physician, physician_user_id="forged-reviewer").status_code == 422
    assert review(client, visit, binding, physician, verifies_model_findings=True).status_code == 422
    assert current(client, visit, binding["binding"]["id"])["review_status"] == "unverified"


def test_withdrawn_report_invalidates_confirmed_binding_even_with_unchanged_content_hash(
    client, visit, inputs, physician,
):
    binding = propose(client, visit, inputs["report"])
    confirmed = review(client, visit, binding, physician)
    assert confirmed.status_code == 201, confirmed.text
    saved = create_run(client, visit, key="before-source-withdrawal")
    assert saved.status_code == 201, saved.text
    changed = client.post(f"/api/v1/paraclinical-reports/{inputs['report']['id']}/entered-in-error",
                          headers=physician, json={"reason": "Synthetic source withdrawn for correction."})
    assert changed.status_code == 200, changed.text
    assert changed.json()["content_sha256"] == inputs["report"]["content_sha256"]
    stale = current(client, visit, binding["binding"]["id"])
    assert stale["review_status"] == "verified"  # Historical review is retained.
    assert stale["freshness"] == "stale"
    assert stale["eligible_for_contextual_link"] is False
    assert "imaging_report_not_final" in stale["invalidation_reasons"]
    read = client.get(run_url(visit, saved.json()))
    assert read.status_code == 200, read.text
    assert read.json()["freshness"] == "stale"
    assert "study_bindings_changed" in read.json()["invalidation_reasons"]
    assert review(client, visit, binding, physician, key="confirm-withdrawn-source",
                  previous=stale["latest_review_sha256"]).status_code == 409
    # An idempotent replay returns historical evidence, never a renewed approval.
    assert review(client, visit, binding, physician).json() == confirmed.json()
    assert current(client, visit, binding["binding"]["id"])["eligible_for_contextual_link"] is False
    assert client.get(intelligence_url(visit)).json()["result"]["workflow_state"] == "blocked"


def test_finalized_report_replacement_invalidates_old_binding_without_rewriting_it(
    client, visit, inputs, physician,
):
    binding = propose(client, visit, inputs["report"])
    assert review(client, visit, binding, physician).status_code == 201
    saved = create_run(client, visit, key="before-report-replacement")
    assert saved.status_code == 201, saved.text
    replacement = client.post(f"/api/v1/paraclinical-reports/{inputs['report']['id']}/supersede", json={
        "category": "imaging", "title": "Synthetic revised imaging report",
        "revision_reason": "Synthetic report corrected through its versioned API.",
        "observations": [{"category": "imaging", "code_system": "LOCAL", "code": "SYNTHETIC_EFFUSION",
                          "display_name": "Synthetic revised effusion", "value_type": "boolean",
                          "boolean_value": False, "body_site": "left knee"}],
    })
    assert replacement.status_code == 201, replacement.text
    assert replacement.json()["version"] == inputs["report"]["version"] + 1
    finalized = client.post(f"/api/v1/paraclinical-reports/{replacement.json()['id']}/finalize", headers=physician)
    assert finalized.status_code == 200, finalized.text
    previous = client.get(f"/api/v1/paraclinical-reports/{inputs['report']['id']}")
    assert previous.status_code == 200, previous.text
    assert previous.json()["status"] == "superseded"
    assert previous.json()["content_sha256"] == inputs["report"]["content_sha256"]
    stale = current(client, visit, binding["binding"]["id"])
    assert stale["binding_sha256"] == binding["binding_sha256"]
    assert stale["binding"]["report_id"] == inputs["report"]["id"]
    assert stale["freshness"] == "stale"
    assert stale["eligible_for_contextual_link"] is False
    assert "imaging_report_not_final" in stale["invalidation_reasons"]
    read = client.get(run_url(visit, saved.json()))
    assert read.status_code == 200, read.text
    assert read.json()["freshness"] == "stale"
    assert "study_bindings_changed" in read.json()["invalidation_reasons"]
    assert review(client, visit, binding, physician, key="confirm-replaced-report",
                  previous=stale["latest_review_sha256"]).status_code == 409


def test_source_finalizer_role_change_invalidates_link_without_changing_context_hash(
    client, visit, inputs, physician,
):
    binding = propose(client, visit, inputs["report"])
    assert review(client, visit, binding, physician).status_code == 201
    saved = create_run(client, visit, key="before-finalizer-role-change")
    assert saved.status_code == 201, saved.text
    context_url = f"/api/v1/visits/{visit['id']}/clinical-context"
    context_before = client.get(context_url).json()["clinical_context_sha256"]
    report = client.get(f"/api/v1/paraclinical-reports/{inputs['report']['id']}").json()
    other_physician = create_role_headers(client, username="binding_second_physician", role="physician")
    demoted = client.patch(f"/api/v1/users/{report['finalized_by_user_id']}", json={"role": "operator"})
    assert demoted.status_code == 200, demoted.text
    assert client.get(context_url).json()["clinical_context_sha256"] == context_before
    stale = current(client, visit, binding["binding"]["id"])
    assert stale["freshness"] == "stale"
    assert stale["eligible_for_contextual_link"] is False
    assert "imaging_report_not_physician_finalized" in stale["invalidation_reasons"]
    read = client.get(run_url(visit, saved.json()))
    assert read.status_code == 200, read.text
    assert read.json()["freshness"] == "stale"
    assert "study_bindings_changed" in read.json()["invalidation_reasons"]
    assert review(client, visit, binding, other_physician, key="confirm-demoted-source",
                  previous=stale["latest_review_sha256"]).status_code == 409


def test_study_binding_dependency_change_during_read_only_composition_returns_conflict(
    client, visit, inputs, monkeypatch,
):
    from backend.app.services.clinical_integration import read_only
    propose(client, visit, inputs["report"])
    original_inventory = read_only.binding_inventory
    count = 0

    def concurrently_changed(*args, **kwargs):
        nonlocal count
        result = original_inventory(*args, **kwargs)
        count += 1
        # Simulate a different binding/review inventory committed while the core
        # adapters ran. A valid typed digest must be compared on the final read.
        return result if count == 1 else result.model_copy(update={"sha256": "f" * 64})

    monkeypatch.setattr(read_only, "binding_inventory", concurrently_changed)
    response = client.get(intelligence_url(visit))
    assert count >= 2
    assert response.status_code == 409, response.text
    assert "Synthetic" not in response.text


def test_service_reloads_database_roles_instead_of_trusting_forged_actor_attributes(
    client, visit, inputs, db_session,
):
    from types import SimpleNamespace
    from backend.app.models.user import User
    from backend.app.schemas.clinical_study_binding import StudyBindingCreate, StudyBindingReviewCreate
    from backend.app.services.clinical_study_binding import StudyBindingService
    from backend.app.services.clinical_integration.service import IntegrationAuthorizationError

    binding = propose(client, visit, inputs["report"])
    create_role_headers(client, username="binding_fake_physician", role="operator")
    operator = db_session.scalar(select(User).where(User.username == "binding_fake_physician"))
    forged = SimpleNamespace(id=operator.id, role="physician", is_active=True)
    create_payload = StudyBindingCreate.model_validate(binding_body(
        client, visit, inputs["report"], key="forged-actor-proposal", previous=binding["binding_sha256"],
    ))
    review_data = StudyBindingReviewCreate.model_validate(review_payload(binding))
    operations = (
        lambda: StudyBindingService.list(db_session, visit["id"], actor=forged),
        lambda: StudyBindingService.get(db_session, visit["id"], binding["binding"]["id"], actor=forged),
        lambda: StudyBindingService.create(db_session, visit["id"], create_payload, actor=forged),
        lambda: StudyBindingService.review(db_session, visit["id"], binding["binding"]["id"],
                                          review_data, actor=forged),
    )
    for operation in operations:
        with pytest.raises(IntegrationAuthorizationError):
            operation()
    assert db_session.scalar(select(ClinicalStudyBindingReview)) is None
    assert len(db_session.scalars(select(ClinicalStudyBinding)).all()) == 1


def test_demoted_physician_cannot_use_stale_token_or_in_memory_actor_for_binding_access(
    client, visit, inputs, db_session,
):
    from types import SimpleNamespace
    from backend.app.models.user import User
    from backend.app.services.clinical_study_binding import StudyBindingService
    from backend.app.services.clinical_integration.service import IntegrationAuthorizationError

    headers = create_role_headers(client, username="binding_demoted_physician", role="physician")
    actor = db_session.scalar(select(User).where(User.username == "binding_demoted_physician"))
    stale_actor = SimpleNamespace(id=actor.id, role=actor.role, is_active=actor.is_active)
    assert stale_actor.role == "physician"
    response = client.patch(f"/api/v1/users/{actor.id}", json={"role": "operator"})
    assert response.status_code == 200, response.text
    assert client.get(bindings_url(visit), headers=headers).status_code in {401, 403}
    with pytest.raises(IntegrationAuthorizationError):
        StudyBindingService.list(db_session, visit["id"], actor=stale_actor)


def test_confirmed_study_association_never_promotes_ai_model_findings(client, visit, inputs, physician):
    from backend.app.api.routes.clinical_integration import get_integration_adapters
    from backend.app.main import app
    from backend.app.services.clinical_integration.adapters import local_adapters
    from backend.tests.test_clinical_integration import MutableAdapter

    binding = propose(client, visit, inputs["report"])
    assert review(client, visit, binding, physician).status_code == 201
    imaging = MutableAdapter("imaging")
    imaging.mode = "model"
    app.dependency_overrides[get_integration_adapters] = lambda: {**local_adapters(), "imaging": imaging}
    response = client.get(intelligence_url(visit))
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["study_bindings"]["bindings"][0]["eligible_for_contextual_link"] is True
    assert data["study_bindings"]["bindings"][0]["verifies_model_findings"] is False
    assert all(item["core"] != "imaging" for item in data["result"]["confirmed_findings"])
    imaging_findings = [item for item in data["result"]["unreviewed_findings"] if item["core"] == "imaging"]
    assert len(imaging_findings) == 1
    assert imaging_findings[0]["review_status"] == "unreviewed_model"
    assert imaging_findings[0]["approval"] is None
    assert imaging_findings[0]["usable_as_confirmed_finding"] is False
    assert data["result"]["workflow_state"] == "blocked"
    assert data["is_diagnosis"] is data["is_clinical_clearance"] is data["authorizes_treatment"] is False
    run = create_run(client, visit, key="confirmed-study-unreviewed-model")
    assert run.status_code == 201, run.text
    assert all(item["core"] != "imaging" for item in run.json()["result"]["confirmed_findings"])
    assert run.json()["result"]["unreviewed_findings"][0]["review_status"] == "unreviewed_model"


@pytest.mark.parametrize("projection", ["inventory", "detail"])
def test_binding_get_rechecks_source_context_before_returning_current_evidence(
    client, visit, inputs, physician, monkeypatch, projection,
):
    from backend.app.services import clinical_study_binding as service

    binding = propose(client, visit, inputs["report"])
    assert review(client, visit, binding, physician).status_code == 201
    original = service.PhysicianCopilotService.get_snapshot
    calls = 0

    def changed_between_reads(*args, **kwargs):
        nonlocal calls
        observed = original(*args, **kwargs)
        calls += 1
        if calls == 1:
            return observed
        return observed.model_copy(update={"manifest": observed.manifest.model_copy(update={
            "clinical_context_sha256": "f" * 64,
        })})

    monkeypatch.setattr(service.PhysicianCopilotService, "get_snapshot", changed_between_reads)
    url = bindings_url(visit)
    if projection == "detail":
        url += f"/{binding['binding']['id']}"
    response = client.get(url)
    assert calls >= 2
    assert response.status_code == 409, response.text
