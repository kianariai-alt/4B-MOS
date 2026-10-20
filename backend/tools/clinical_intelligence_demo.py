"""Fixed fictional knee/MRI exchange: no database, network or trained model.

Run: python -m backend.tools.clinical_intelligence_demo
"""

from datetime import datetime, timezone

from backend.app.schemas.clinical_integration import (
    ClinicalAssessmentReference, ImagingStudyReference, IntegrationIssue, PhysicianApproval, VisitReference,
)
from backend.app.schemas.clinical_intelligence import ClinicalSafetyStatus
from backend.app.services.clinical_integration.decision import (
    MockDecisionAdapter, MockImagingAdapter, MockOrthopedicAdapter, collect_decision, synthetic_core_input,
)
from backend.app.services.clinical_integration.engine import assemble_result, collect_cores, digest_model
from backend.app.services.clinical_integration.read_only import make_snapshot


def synthetic_snapshot():
    now = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
    context = synthetic_core_input()
    adapters = {"orthopedic": MockOrthopedicAdapter(now=now), "imaging": MockImagingAdapter(now=now)}
    cores, issues = collect_cores(context, adapters, now=now)
    decision = collect_decision(context, MockDecisionAdapter(now=now), now=now)
    clinical, imaging = context.observations
    result = assemble_result(
        patient_id="synthetic-knee-patient", visit=VisitReference(visit_id=context.visit_id, status="open"),
        context=context, assessment=ClinicalAssessmentReference(
            intake_id=clinical.source.record_id, version=clinical.source.version,
            content_sha256=clinical.source.content_sha256, body_region="knee", laterality="left",
        ),
        studies=(ImagingStudyReference(
            report_id=imaging.source.record_id, version=imaging.source.version,
            content_sha256=imaging.source.content_sha256,
        ),),
        # Fabricated attribution only; an actual approval requires existing
        # authenticated finalization/audit flows, never this demo.
        approvals={digest_model(clinical.source): PhysicianApproval(
            physician_user_id="synthetic-physician", reviewed_at=now,
        )},
        cores=cores, knowledge=(), copilot_sha256="d" * 64, safety_rule_set_sha256="e" * 64,
        issues=issues + (
            IntegrationIssue(code="synthetic_fixture_not_clinically_validated", severity="blocking"),
            IntegrationIssue(code="safety_evaluation_missing", severity="blocking"),
            IntegrationIssue(code="decision_requires_physician_review", severity="blocking"),
        ), now=now,
    )
    return make_snapshot(result, images=(), decision=decision,
                         safety=ClinicalSafetyStatus(status="missing"), now=now)


if __name__ == "__main__":
    print(synthetic_snapshot().model_dump_json(indent=2))
