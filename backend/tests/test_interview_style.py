"""Approved workflow context for Copilot is separate from model training."""
import pytest

from backend.app.schemas.physician_questions import BankReview
from backend.app.services.interview_style import approved_interview_style, copilot_with_interview_style
from backend.app.services.physician_questions import PhysicianQuestionService
from backend.app.services.session_finalization import evidence_digest
from backend.app.services.visit_learning import VisitLearningService, VisitLearningAuthorizationError
from backend.tests.test_visit_learning import prepare, submit, promotion, grant, user, configure_local_crypto


def test_submitted_or_promoted_draft_is_not_an_active_style(db_session):
    context = prepare(db_session)
    actor, visit_id = context["actor"], context["visit"].id
    packet = submit(db_session, context)
    assert not approved_interview_style(db_session, visit_id, actor=actor).has_approved_bank
    promoted = VisitLearningService.promote_to_bank_draft(db_session, packet.summary.packet_id,
                                                        promotion(packet), actor=actor)
    assert promoted.bank_event.action == "draft"
    style = approved_interview_style(db_session, visit_id, actor=actor)
    assert style.bank is None and not style.has_approved_bank
    assert not style.model_weights_trained and not style.authorizes_diagnosis


def approved_fixture(db):
    context = prepare(db)
    actor = context["actor"]
    packet = submit(db, context)
    promoted = VisitLearningService.promote_to_bank_draft(db, packet.summary.packet_id, promotion(packet), actor=actor)
    draft = promoted.bank_event
    bank = PhysicianQuestionService.review(db, actor.id, BankReview(
        expected_version=draft.version, expected_bank_sha256=draft.sha256,
        request_key="synthetic-style-approve", statement_fa="پرسش‌ها و ترجیح خلاصه را برای استفادهٔ محدود در گردش کار مرور کردم.",
    ), actor=actor, action="approve")
    return context, packet, bank


def test_only_explicit_approval_enters_the_source_bound_style(db_session):
    context, packet, bank = approved_fixture(db_session)
    style = approved_interview_style(db_session, context["visit"].id, actor=context["actor"])
    assert style.has_approved_bank and style.bank_sha256 == bank.sha256
    assert style.bank.questions == bank.content.questions
    assert style.learning_source_packet_id == packet.summary.packet_id
    assert style.style_sha256 == evidence_digest(style.model_dump(mode="json", exclude={"style_sha256"}))


def test_revocation_blocks_new_style_reader_without_automatic_bank_retirement(db_session):
    context, _, _ = approved_fixture(db_session)
    grant(db_session, context["visit"].id, context["actor"], "educational_use", state="withdrawn")
    with pytest.raises(VisitLearningAuthorizationError):
        approved_interview_style(db_session, context["visit"].id, actor=context["actor"])
    assert PhysicianQuestionService.workspace(db_session, context["actor"].id, actor=context["actor"]).has_approved_bank


def test_another_physician_cannot_apply_the_style_to_this_visit(db_session):
    context = prepare(db_session)
    with pytest.raises(VisitLearningAuthorizationError):
        approved_interview_style(db_session, context["visit"].id, actor=user(db_session))


def test_copilot_adapter_preserves_existing_snapshot_and_binds_approved_style(db_session, monkeypatch):
    context, _, _ = approved_fixture(db_session)
    from backend.app.services.physician_copilot import PhysicianCopilotService
    snapshot = PhysicianCopilotService.get_snapshot(db_session, context["visit"].id)
    result = copilot_with_interview_style(db_session, context["visit"].id, actor=context["actor"])
    assert result.clinical_snapshot.snapshot_sha256 == snapshot.snapshot_sha256
    assert result.interview_style.has_approved_bank and not result.model_weights_trained
    assert result.result_sha256 == evidence_digest({"schema_version": "1.0.0",
        "clinical_snapshot_sha256": result.clinical_snapshot.snapshot_sha256,
        "interview_style_sha256": result.interview_style.style_sha256})
