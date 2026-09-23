from fastapi.testclient import TestClient

from backend.app.core.config import settings
from backend.app.main import CLINICAL_CONSOLE_CSP, create_application


SECURITY_HEADERS = {
    "cache-control": "no-store",
    "content-security-policy": CLINICAL_CONSOLE_CSP,
    "permissions-policy": "camera=(), geolocation=(), microphone=()",
    "referrer-policy": "no-referrer",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
}


def assert_console_security_headers(response):
    for name, expected in SECURITY_HEADERS.items():
        assert response.headers[name] == expected


def test_console_path_redirects_to_trailing_slash(client):
    response = client.get(
        "/app",
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"].endswith("/app/")
    assert_console_security_headers(response)


def test_console_shell_is_public_but_contains_no_clinical_data(client):
    response = client.get("/app/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert_console_security_headers(response)

    html = response.text
    assert '<html lang="fa" dir="rtl">' in html
    assert "4B-MOS | کنسول بالینی" in html
    assert 'id="login-form"' in html
    assert 'id="copilot-workspace"' in html
    assert 'id="copilot-visit-form"' in html
    assert 'id="load-copilot-button"' in html
    assert 'id="copilot-roadmap"' in html
    assert 'id="copilot-decision-section"' in html
    assert 'id="copilot-decision-form"' in html
    assert 'id="copilot-decision-history"' in html
    assert 'id="copilot-outcomes"' in html
    assert 'id="learning-workspace"' in html
    assert 'id="load-learning-button"' in html
    assert 'id="learning-summary"' in html
    assert 'id="learning-protocols"' in html
    assert 'id="learning-governance-signals"' in html
    assert 'id="learning-governance-cases"' in html
    assert 'id="evidence-workspace"' in html
    assert 'id="evidence-brief-form"' in html
    assert 'id="safety-workspace"' in html
    assert 'id="safety-visit-form"' in html
    assert 'id="run-safety-evaluation-button"' in html
    assert 'id="safety-escalations"' in html
    assert 'id="load-safety-escalations-button"' in html
    assert 'id="pilot-readiness-tab"' in html
    assert 'id="pilot-readiness-workspace"' in html
    assert 'id="load-pilot-readiness-button"' in html
    assert 'id="pilot-readiness-summary"' in html
    assert 'id="pilot-readiness-checks"' in html
    assert 'id="pilot-manual-gates"' in html
    assert 'id="pilot-launch-preview"' in html
    assert 'id="pilot-launch-history"' in html
    assert 'id="freeze-pilot-launch-package-button"' in html
    assert "هیچ موردی از پیش انتخاب نمی‌شود" in html
    assert "جایگزین قضاوت مستقل پزشک نمی‌شود" in html
    assert "وجود نداشتن یافته، مجوز بالینی نیست" in html
    assert 'src="/app/app.js"' in html
    assert 'href="/app/app.css"' in html
    assert "patient_name" not in html
    assert "access_token" not in html
    assert "onclick=" not in html
    assert "<style" not in html


def test_console_assets_are_same_origin_and_not_cached(client):
    javascript = client.get("/app/app.js")
    stylesheet = client.get("/app/app.css")

    assert javascript.status_code == 200
    assert javascript.headers["content-type"].startswith(
        "text/javascript"
    )
    assert_console_security_headers(javascript)

    assert stylesheet.status_code == 200
    assert stylesheet.headers["content-type"].startswith("text/css")
    assert_console_security_headers(stylesheet)

    source = javascript.text
    assert 'const API_BASE = "/api/v1"' in source
    assert 'apiRequest("/auth/login"' in source
    assert 'apiRequest("/auth/me")' in source
    assert 'apiRequest("/dashboard/live-flow")' in source
    assert "/physician-copilot`" in source
    assert "COPILOT_READ_ROLES" in source
    assert "currentCopilotSnapshot" in source
    assert "snapshot.treatment_outcomes" in source
    assert "/treatment-options-roadmap" in source
    assert "renderTreatmentRoadmap" in source
    assert "roadmap.options" in source
    assert "/treatment-decisions" in source
    assert "/learning/governance/signals" in source
    assert "/protocol-governance/cases" in source
    assert "renderGovernanceSignals" in source
    assert "renderGovernanceCases" in source
    assert "executeGovernanceRelease" in source
    assert "/release`" in source
    assert "item.release" in source
    assert "createGovernanceRecoveryCase" in source
    assert "executeGovernanceRecovery" in source
    assert "item.recovery" in source
    assert "recoverySourceReleaseIds" in source
    assert 'apiRequest("/pilot-readiness")' in source
    assert "renderPilotReadiness" in source
    assert "canReadPilotReadiness" in source
    assert 'apiRequest("/pilot-readiness/manual-gates")' in source
    assert "createPilotManualAttestation" in source
    assert "reviewPilotManualAttestation" in source
    assert "pilot-attestation-form" in source
    assert "pilot-review-form" in source
    assert "readiness_sha256" in source
    assert "renderPilotLaunchPackage" in source
    assert "freezePilotLaunchPackage" in source
    assert "/launch-package-preview" in source
    assert "/launch-packages" in source
    assert "createTreatmentDecision" in source
    assert "currentTreatmentDecisions" in source
    assert "selectedDecisionProtocols" in source
    assert "roadmap.ranks_treatments" not in source
    assert "outcome.patient_rating" in source
    assert "/clinical-context`" in source
    assert "/evidence-briefs`" in source
    assert "/safety-inbox`" in source
    assert "/safety-evaluations`" in source
    assert "/safety-findings/${encodeURIComponent" in source
    assert 'apiRequest("/safety/escalations?limit=50")' in source
    assert 'apiRequest("/knowledge/facts/approved?limit=100")' in source
    assert "expected_clinical_context_sha256" in source
    assert "expected_content_sha256" in source
    assert "selectedFacts.clear()" in source
    assert "MAX_SELECTED_FACTS = 20" in source
    assert "resetOperationalState()" in source
    assert "resetSafetyState()" in source
    assert "sessionGeneration" in source
    assert "expected_evaluation_result_sha256" in source
    assert "evaluation_matches_current_context" in source
    assert "is_clinical_priority" in source
    assert "fact.checked = true" not in source
    assert "/workflow`" in source
    assert "textContent" in source
    assert "innerHTML" not in source

    for forbidden_storage in (
        "localStorage",
        "sessionStorage",
        "document.cookie",
        "indexedDB",
    ):
        assert forbidden_storage not in source


def test_console_does_not_weaken_api_authentication(client):
    assert client.get("/app/").status_code == 200

    response = client.get("/api/v1/dashboard/live-flow")

    assert response.status_code == 401


def test_console_remains_available_when_production_docs_are_hidden(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    with TestClient(create_application()) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404

        response = client.get("/app/")
        assert response.status_code == 200
        assert_console_security_headers(response)
