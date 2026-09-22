"""Read-only physician workspace snapshot assembled from governed clinical records."""

from sqlalchemy.orm import Session

from backend.app.schemas.clinical_context import ClinicalContextSnapshotRead
from backend.app.schemas.physician_copilot import (
    PhysicianCopilotManifestRead,
    PhysicianCopilotSnapshotRead,
)
from backend.app.services.clinical_context import ClinicalContextService
from backend.app.services.clinical_evidence import ClinicalEvidenceBriefService
from backend.app.services.clinical_safety import clinical_context_digest
from backend.app.services.clinical_safety_review import (
    ClinicalSafetyFindingReviewService,
)
from backend.app.services.session_finalization import evidence_digest
from backend.app.services.treatment_outcome import TreatmentOutcomeService


class PhysicianCopilotIntegrityError(Exception):
    pass


class PhysicianCopilotService:
    @staticmethod
    def get_snapshot(
        db: Session,
        visit_id: str,
    ) -> PhysicianCopilotSnapshotRead:
        context = ClinicalContextService.get_current_context(db, visit_id)
        context_sha256 = clinical_context_digest(context)
        context_snapshot = ClinicalContextSnapshotRead(
            **context.model_dump(),
            clinical_context_sha256=context_sha256,
        )

        safety_inbox = ClinicalSafetyFindingReviewService.get_inbox(
            db,
            visit_id,
        )
        if safety_inbox.current_clinical_context_sha256 != context_sha256:
            raise PhysicianCopilotIntegrityError(
                "Clinical context changed while the physician snapshot was assembled."
            )

        evidence_briefs = ClinicalEvidenceBriefService.list_for_visit(
            db,
            visit_id,
        )
        evidence_briefs = sorted(
            evidence_briefs,
            key=lambda item: (item.created_at, item.id),
        )
        current_context_evidence_briefs = [
            item
            for item in evidence_briefs
            if item.clinical_context_sha256 == context_sha256
        ]

        treatment_outcomes = TreatmentOutcomeService.list_for_visit(
            db,
            visit_id,
        )
        treatment_outcomes = sorted(
            treatment_outcomes,
            key=lambda item: (item.recorded_at, item.id),
        )

        open_escalations = sorted(
            [
                item
                for item in safety_inbox.findings
                if item.timeline.review_status == "escalated"
            ],
            key=lambda item: item.finding.id,
        )

        review_hashes = [
            item.timeline.reviews[-1].sha256
            for item in open_escalations
        ]
        brief_hashes = [
            item.sha256
            for item in sorted(evidence_briefs, key=lambda item: item.id)
        ]
        outcome_hashes = [
            item.sha256
            for item in sorted(treatment_outcomes, key=lambda item: item.id)
        ]

        manifest = PhysicianCopilotManifestRead(
            clinical_context_sha256=context_sha256,
            safety_evaluation_result_sha256=(
                safety_inbox.evaluation.result_sha256
                if safety_inbox.evaluation is not None
                else None
            ),
            open_escalation_review_sha256s=review_hashes,
            evidence_brief_sha256s=brief_hashes,
            treatment_outcome_sha256s=outcome_hashes,
        )

        return PhysicianCopilotSnapshotRead(
            visit_id=visit_id,
            generated_at=context.generated_at,
            clinical_context=context_snapshot,
            safety_inbox=safety_inbox,
            open_escalations=open_escalations,
            evidence_briefs=evidence_briefs,
            current_context_evidence_briefs=current_context_evidence_briefs,
            treatment_outcomes=treatment_outcomes,
            manifest=manifest,
            snapshot_sha256=evidence_digest(
                {
                    "schema_version": 1,
                    "visit_id": visit_id,
                    "manifest": manifest.model_dump(mode="json"),
                }
            ),
        )
