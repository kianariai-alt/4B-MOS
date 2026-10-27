"""Project current governed reports into a Copilot evidence view, with no writes.

Received PDFs/images and machine proposals are not clinical records. The existing
report lifecycle must establish clinician review and visit association first.
This service does not turn a report into proof of scan identity/completeness.
"""

from backend.app.schemas.clinical_context import ClinicalContextRead
from backend.app.schemas.imaging_evidence import ImagingEvidenceRead, ImagingReportEvidence
from backend.app.services.clinical_context import ClinicalContextService
from backend.app.services.clinical_safety import clinical_context_digest
from backend.app.services.session_finalization import evidence_digest


def project_imaging_evidence(context: ClinicalContextRead) -> ImagingEvidenceRead:
    reports = [
        ImagingReportEvidence(
            report_id=item.id, report_version=item.version,
            report_content_sha256=item.content_sha256, conclusion=item.conclusion,
            observations=[observation for observation in item.observations if observation.category == "imaging"],
        )
        for item in sorted(context.reports, key=lambda item: item.id)
        if item.category == "imaging" and item.status == "final" and item.visit_id == context.visit_id
        and item.finalized_by_user_id is not None and item.finalized_at is not None
    ]
    payload = dict(
        visit_id=context.visit_id, clinical_context_sha256=clinical_context_digest(context), reports=reports,
        missing_data=[] if reports else ["finalized_imaging_report_required"],
    )
    result = ImagingEvidenceRead(**payload, evidence_sha256="0"*64)
    return result.model_copy(update={"evidence_sha256": evidence_digest(result.model_dump(mode="json", exclude={"evidence_sha256"}))})


class ImagingEvidenceService:
    @staticmethod
    def get_for_visit(db, visit_id):
        # Existing service verifies stored report hashes and current final status.
        return project_imaging_evidence(ClinicalContextService.get_current_context(db, visit_id))
