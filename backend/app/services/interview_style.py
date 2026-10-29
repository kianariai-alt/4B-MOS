"""Expose approved interview preferences to a separate Copilot adapter.

The existing clinical snapshot, question-bank authority, medical Registry and
safety engine stay unchanged. Draft learning packets never enter this view.
"""
from backend.app.schemas.interview_style import ApprovedInterviewStyle, PhysicianCopilotWithInterviewStyle
from backend.app.services.physician_questions import PhysicianQuestionService
from backend.app.services.physician_copilot import PhysicianCopilotService
from backend.app.services.reception import ReceptionService
from backend.app.services.session_finalization import evidence_digest
from backend.app.services.visit_learning import VisitLearningAuthorizationError, authorize_approved_bank_source


def approved_interview_style(db, visit_id, *, actor):
    # Existing service rechecks active physician identity and bank ownership.
    bank_workspace = PhysicianQuestionService.workspace(db, actor.id, actor=actor)
    reception = ReceptionService.workspace(db, visit_id)
    assigned = reception.latest_intake.content.get("assigned_physician_id") if reception.latest_intake else None
    if assigned != actor.id:
        raise VisitLearningAuthorizationError("Only the currently assigned physician can read this interview style.")
    active = bank_workspace.active_bank
    origin = authorize_approved_bank_source(db, active, actor=actor) if active else None
    style = ApprovedInterviewStyle(
        visit_id=visit_id, physician_id=actor.id, has_approved_bank=active is not None,
        bank_id=active.id if active else None, bank_sha256=active.sha256 if active else None,
        bank_version=active.version if active else None, bank=active.content if active else None,
        learning_source_packet_id=origin, style_sha256="0" * 64,
    )
    return style.model_copy(update={"style_sha256": evidence_digest(style.model_dump(mode="json", exclude={"style_sha256"}))})


def copilot_with_interview_style(db, visit_id, *, actor):
    style = approved_interview_style(db, visit_id, actor=actor)
    clinical = PhysicianCopilotService.get_snapshot(db, visit_id)
    return PhysicianCopilotWithInterviewStyle(
        clinical_snapshot=clinical, interview_style=style,
        result_sha256=evidence_digest({"schema_version": "1.0.0", "clinical_snapshot_sha256": clinical.snapshot_sha256,
                                       "interview_style_sha256": style.style_sha256}),
    )
