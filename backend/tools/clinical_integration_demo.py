"""Synthetic composition only; never opens a database or a network connection.

Run: python -m backend.tools.clinical_integration_demo
"""

from datetime import datetime, timezone
import json

from backend.app.schemas.clinical_context import ParaclinicalObservationInput
from backend.app.schemas.clinical_integration import (
    ClinicalAssessmentReference, CoreInput, ImagingStudyReference, IntegrationIssue,
    PhysicianApproval, RecordReference, SourceObservation, VisitReference,
)
from backend.app.services.clinical_integration.adapters import local_adapters
from backend.app.services.clinical_integration.engine import assemble_result, collect_cores, digest_model


def synthetic_result():
    now = datetime.now(timezone.utc)
    clinical = SourceObservation(
        source=RecordReference(record_type="clinical_intake", record_id="synthetic-intake",
                               version=1, content_sha256="a" * 64, field="exam_findings"),
        observation=ParaclinicalObservationInput(
            category="clinical_test", code_system="LOCAL", code="INTAKE_EXAM",
            display_name="Synthetic examination", value_type="string",
            string_value="Synthetic limited knee movement; not a real patient.", body_site="left knee",
        ),
    )
    imaging = SourceObservation(
        source=RecordReference(record_type="paraclinical_report", record_id="synthetic-report",
                               version=1, content_sha256="b" * 64,
                               field="observation", observation_id="synthetic-imaging-observation"),
        observation=ParaclinicalObservationInput(
            category="imaging", code_system="LOCAL", code="SYNTHETIC_EFFUSION",
            display_name="Synthetic imaging finding", value_type="boolean",
            boolean_value=True, body_site="left knee",
        ),
    )
    context = CoreInput(visit_id="synthetic-visit", clinical_context_sha256="c" * 64,
                        observations=(clinical, imaging))
    cores, issues = collect_cores(context, local_adapters(), now=now)
    return assemble_result(
        patient_id="synthetic-patient", visit=VisitReference(visit_id="synthetic-visit", status="open"),
        context=context, assessment=ClinicalAssessmentReference(
            intake_id="synthetic-intake", version=1, content_sha256="a" * 64,
            body_region="knee", laterality="left",
        ),
        studies=(ImagingStudyReference(report_id="synthetic-report", version=1, content_sha256="b" * 64),),
        approvals={digest_model(item.source): PhysicianApproval(
            physician_user_id="synthetic-physician", reviewed_at=now,
        ) for item in context.observations},
        cores=cores, knowledge=(), copilot_sha256="d" * 64, safety_rule_set_sha256="e" * 64,
        issues=issues + (IntegrationIssue(code="synthetic_demo_not_clinically_validated", severity="warning"),),
        now=now,
    )


if __name__ == "__main__":
    print(json.dumps(synthetic_result().model_dump(mode="json"), ensure_ascii=False, indent=2))
