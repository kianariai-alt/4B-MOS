"""Visit-locked persistence, replay, freshness and human review boundaries."""

from datetime import datetime, timezone
import uuid

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.db.clinical_record_transactions import clinical_record_write
from backend.app.models.clinical_integration import ClinicalIntegrationReview, ClinicalIntegrationRun
from backend.app.models.user import User
from backend.app.models.visit import Visit
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.schemas.clinical_integration import (
    ClinicalEvidenceReference, IntegrationAuditEvent, IntegrationCopilotView, IntegrationIssue, IntegrationReviewCreate,
    IntegrationRunCreate, IntegrationRunRead, IntegrationRunSnapshot, PhysicianReview, VisitReference,
)
from backend.app.services.audit_context import actor_data
from backend.app.services.clinical_integration.adapters import approved_knowledge, local_adapters, source_bundle, utc
from backend.app.services.clinical_integration.engine import ENGINE_VERSION, assemble_result, collect_cores, digest_model
from backend.app.services.clinical_safety import ClinicalSafetyRuleService, safety_rule_set_digest
from backend.app.services.physician_copilot import PhysicianCopilotService
from backend.app.services.session_finalization import evidence_digest


class IntegrationConflictError(Exception):
    pass


class IntegrationNotFoundError(Exception):
    pass


class IntegrationAuthorizationError(Exception):
    pass


class IntegrationIntegrityError(Exception):
    pass


def _require_actor(db, actor, *, physician_only=False):
    current = db.get(User, actor.id, populate_existing=True) if actor else None
    if (current is None or not current.is_active
            or current.role not in ({"physician"} if physician_only else {"admin", "physician"})):
        raise IntegrationAuthorizationError("An active authorized clinician is required.")
    return current


def _visit(db, visit_id):
    record = db.get(Visit, visit_id, populate_existing=True)
    if record is None:
        raise IntegrationNotFoundError("Visit was not found.")
    return record


def _rules_hash(db, now):
    return safety_rule_set_digest(ClinicalSafetyRuleService.list_active(db, as_of=now.date()))


def _request_hash(payload, actor):
    value = payload.model_dump(mode="json")
    value["knowledge_fact_ids"] = sorted(value["knowledge_fact_ids"])
    return evidence_digest({"request": value, "actor_user_id": actor.id})


def _verify_run(record) -> IntegrationRunSnapshot:
    try:
        snapshot = IntegrationRunSnapshot.model_validate(record.payload)
        if (evidence_digest(record.payload) != record.result_sha256
                or snapshot.id != record.id
                or snapshot.result.visit.visit_id != record.visit_id
                or snapshot.created_by_user_id != record.created_by_user_id
                or snapshot.request_sha256 != record.request_sha256
                or snapshot.created_at != utc(record.created_at)):
            raise ValueError("Snapshot metadata mismatch.")
        return snapshot
    except (ValidationError, ValueError, TypeError) as error:
        raise IntegrationIntegrityError("Integration snapshot integrity check failed.") from error


def _reviews(db, record):
    result = []
    rows = db.scalars(select(ClinicalIntegrationReview).where(
        ClinicalIntegrationReview.run_id == record.id,
    ).order_by(ClinicalIntegrationReview.created_at, ClinicalIntegrationReview.id)).all()
    for row in rows:
        try:
            review = PhysicianReview.model_validate(row.payload)
            if (digest_model(review) != row.sha256 or review.id != row.id
                    or review.run_id != record.id or review.visit_id != record.visit_id
                    or review.result_sha256 != record.result_sha256
                    or review.physician_user_id != row.physician_user_id
                    or review.reviewed_at != utc(row.created_at)):
                raise ValueError("Review metadata mismatch.")
        except (ValidationError, ValueError, TypeError) as error:
            raise IntegrationIntegrityError("Integration review integrity check failed.") from error
        result.append(review)
    return tuple(result)


def _freshness(db, result, *, adapters, now, lock=False):
    reasons = []
    unverifiable = False
    if result.valid_until <= now:
        reasons.append("review_window_expired")
    if result.provenance.engine_version != ENGINE_VERSION:
        reasons.append("integration_engine_changed")
    try:
        db.expire_all()
        visit = _visit(db, result.visit.visit_id)
        if visit.status != result.visit.status or visit.patient_id != result.patient.patient_id:
            reasons.append("visit_changed")
        copilot = PhysicianCopilotService.get_snapshot(db, result.visit.visit_id)
        if copilot.snapshot_sha256 != result.provenance.copilot_snapshot_sha256:
            reasons.append("copilot_dependencies_changed")
        if copilot.manifest.clinical_context_sha256 != result.provenance.clinical_context_sha256:
            reasons.append("clinical_context_changed")
        if _rules_hash(db, now) != result.provenance.safety_rule_set_sha256:
            reasons.append("safety_rules_changed")
        bundle = source_bundle(db, copilot.clinical_context, copilot.manifest.clinical_context_sha256)
        for finding in result.confirmed_findings:
            if bundle.approvals.get(digest_model(finding.finding.source)) != finding.approval:
                reasons.append("source_review_changed")
                break
        try:
            current_knowledge = approved_knowledge(
                db, tuple(item.fact_id for item in result.knowledge), as_of=now.date(), lock=lock,
            )
            if current_knowledge != result.knowledge:
                reasons.append("knowledge_version_changed")
        except (ValueError, LookupError):
            reasons.append("knowledge_no_longer_valid")
    except SQLAlchemyError as error:
        raise IntegrationConflictError("Integration dependencies are temporarily unavailable.") from error
    except Exception:
        # Treat any unreadable dependency as unavailable for approval. Never
        # return exception text from clinical records or a downstream service.
        reasons.append("dependencies_unverifiable")
        unverifiable = True
    for core in result.cores:
        try:
            if adapters[core.core].current_version() != core.component:
                reasons.append(f"{core.core}_component_changed")
        except Exception:
            reasons.append(f"{core.core}_component_unverifiable")
            unverifiable = True
    return ("unverifiable" if unverifiable else "stale" if reasons else "current"), tuple(dict.fromkeys(reasons))


def _read(db, record, *, adapters, lock=False):
    snapshot = _verify_run(record)
    freshness, reasons = _freshness(
        db, snapshot.result, adapters=adapters, now=datetime.now(timezone.utc), lock=lock,
    )
    return IntegrationRunRead(
        id=record.id, result_sha256=record.result_sha256, result=snapshot.result,
        freshness=freshness, invalidation_reasons=reasons, reviews=_reviews(db, record),
    )


class ClinicalIntegrationService:
    @staticmethod
    @clinical_record_write
    def create(db: Session, visit_id: str, payload: IntegrationRunCreate, *, actor: User, adapters=None):
        actor = _require_actor(db, actor)
        adapters = local_adapters() if adapters is None else adapters
        visit = _visit(db, visit_id)
        request_hash = _request_hash(payload, actor)
        previous = db.scalar(select(ClinicalIntegrationRun).where(
            ClinicalIntegrationRun.visit_id == visit_id,
            ClinicalIntegrationRun.request_key == payload.request_key,
        ))
        if previous is not None:
            if previous.request_sha256 != request_hash:
                raise IntegrationConflictError("Request key was already used for different inputs or actor.")
            return _read(db, previous, adapters=adapters)
        now = datetime.now(timezone.utc)
        copilot = PhysicianCopilotService.get_snapshot(db, visit_id)
        if copilot.manifest.clinical_context_sha256 != payload.expected_clinical_context_sha256:
            raise IntegrationConflictError("Clinical context changed; reload before creating a run.")
        try:
            knowledge = approved_knowledge(db, payload.knowledge_fact_ids, as_of=now.date(), lock=True)
        except ValueError as error:
            raise IntegrationConflictError("Selected knowledge is not approved and current.") from error
        rules_hash = _rules_hash(db, now)
        bundle = source_bundle(db, copilot.clinical_context, copilot.manifest.clinical_context_sha256)
        cores, issues = collect_cores(bundle.core_input, adapters, now=now)
        issues = list(issues + bundle.issues)
        safety = copilot.safety_inbox
        if safety.evaluation is None:
            issues.append(IntegrationIssue(code="safety_evaluation_missing", severity="blocking"))
        elif (safety.evaluation_matches_current_context is not True
              or safety.evaluation.rule_set_sha256 != rules_hash):
            issues.append(IntegrationIssue(code="safety_evaluation_stale", severity="blocking"))
        elif safety.evaluation.outcome == "alerts_present" or copilot.open_escalations:
            issues.append(IntegrationIssue(code="safety_alerts_require_review", severity="blocking"))
        elif safety.evaluation.outcome == "no_active_rules":
            issues.append(IntegrationIssue(code="no_active_safety_rules", severity="warning"))
        result = assemble_result(
            patient_id=visit.patient_id, visit=VisitReference(visit_id=visit.id, status=visit.status),
            context=bundle.core_input, assessment=bundle.assessment, studies=bundle.studies,
            approvals=bundle.approvals, cores=cores, knowledge=knowledge,
            copilot_sha256=copilot.snapshot_sha256, safety_rule_set_sha256=rules_hash,
            issues=tuple(issues), now=now,
            evidence_briefs=tuple(ClinicalEvidenceReference(
                brief_id=brief.id, content_sha256=brief.sha256,
                clinical_context_sha256=brief.clinical_context_sha256,
                knowledge_set_sha256=brief.knowledge_set_sha256,
                context_matches=(brief.clinical_context_sha256 == copilot.manifest.clinical_context_sha256),
            ) for brief in copilot.evidence_briefs),
        )
        snapshot = IntegrationRunSnapshot(
            id=str(uuid.uuid4()), request_sha256=request_hash,
            created_by_user_id=actor.id, created_at=now, result=result,
        )
        record = ClinicalIntegrationRun(
            id=snapshot.id, visit_id=visit_id, request_key=payload.request_key,
            request_sha256=request_hash, created_by_user_id=actor.id, created_at=now,
            payload=snapshot.model_dump(mode="json"), result_sha256=digest_model(snapshot),
        )
        db.add(record)
        db.flush()
        AuditLogRepository.create(
            db, commit=False, entity_type="clinical_integration", entity_id=record.id,
            event_type="integration_run_created", to_state=result.workflow_state,
            event_data={"result_sha256": record.result_sha256, "issue_count": len(result.issues)},
            **actor_data(actor),
        )
        return _read(db, record, adapters=adapters, lock=True)

    @staticmethod
    def get(db, visit_id, run_id, *, actor, adapters=None):
        _require_actor(db, actor)
        _visit(db, visit_id)
        record = db.get(ClinicalIntegrationRun, run_id, populate_existing=True)
        if record is None or record.visit_id != visit_id:
            raise IntegrationNotFoundError("Integration run was not found for this visit.")
        return _read(db, record, adapters=local_adapters() if adapters is None else adapters)

    @staticmethod
    @clinical_record_write
    def review(db, visit_id: str, run_id: str, payload: IntegrationReviewCreate, *, actor, adapters=None):
        actor = _require_actor(db, actor, physician_only=True)
        run = ClinicalIntegrationService.get(db, visit_id, run_id, actor=actor, adapters=adapters)
        previous = db.scalar(select(ClinicalIntegrationReview).where(
            ClinicalIntegrationReview.run_id == run_id,
            ClinicalIntegrationReview.request_key == payload.request_key,
        ))
        if previous is not None:
            review = next(item for item in run.reviews if item.id == previous.id)
            if (review.physician_user_id != actor.id or review.action != payload.action
                    or review.rationale != payload.rationale
                    or review.result_sha256 != payload.expected_result_sha256):
                raise IntegrationConflictError("Review key was already used for a different decision.")
            return review
        if payload.expected_result_sha256 != run.result_sha256:
            raise IntegrationConflictError("Review must reference the exact integration snapshot.")
        # Recheck under shared knowledge locks before recording an approval.
        freshness, _ = _freshness(db, run.result, adapters=local_adapters() if adapters is None else adapters,
                                 now=datetime.now(timezone.utc), lock=True)
        if payload.action == "approve_summary" and (
            freshness != "current" or run.result.workflow_state != "awaiting_physician_review"
        ):
            raise IntegrationConflictError("Blocked, stale or unverifiable summaries cannot be approved.")
        review = PhysicianReview(
            id=str(uuid.uuid4()), run_id=run_id, visit_id=visit_id, physician_user_id=actor.id,
            result_sha256=run.result_sha256, action=payload.action, rationale=payload.rationale,
            reviewed_at=datetime.now(timezone.utc),
        )
        db.add(ClinicalIntegrationReview(
            id=review.id, run_id=run_id, request_key=payload.request_key,
            physician_user_id=actor.id, created_at=review.reviewed_at,
            payload=review.model_dump(mode="json"), sha256=digest_model(review),
        ))
        db.flush()
        AuditLogRepository.create(
            db, commit=False, entity_type="clinical_integration", entity_id=run_id,
            event_type="integration_physician_reviewed",
            event_data={"result_sha256": run.result_sha256, "review_id": review.id,
                        "review_sha256": digest_model(review), "action": review.action},
            **actor_data(actor),
        )
        return review

    @staticmethod
    def copilot_view(db, visit_id, *, actor, adapters=None):
        _require_actor(db, actor)
        _visit(db, visit_id)
        copilot = PhysicianCopilotService.get_snapshot(db, visit_id)
        latest = db.scalar(select(ClinicalIntegrationRun).where(
            ClinicalIntegrationRun.visit_id == visit_id,
        ).order_by(ClinicalIntegrationRun.created_at.desc(), ClinicalIntegrationRun.id.desc()).limit(1))
        run = (ClinicalIntegrationService.get(db, visit_id, latest.id, actor=actor,
                                              adapters=adapters) if latest else None)
        # Fail rather than label two observations from different moments as one
        # current combined view during concurrent context changes.
        current = PhysicianCopilotService.get_snapshot(db, visit_id)
        if current.snapshot_sha256 != copilot.snapshot_sha256:
            raise IntegrationConflictError("Copilot changed while assembling the combined view.")
        return IntegrationCopilotView(
            visit_id=visit_id, copilot_snapshot_sha256=copilot.snapshot_sha256,
            clinical_context_sha256=copilot.manifest.clinical_context_sha256,
            latest_run=run,
        )

    @staticmethod
    def audit(db, visit_id, run_id, *, actor):
        ClinicalIntegrationService.get(db, visit_id, run_id, actor=actor)
        rows = AuditLogRepository.list_by_entity(db, entity_type="clinical_integration", entity_id=run_id)
        return tuple(IntegrationAuditEvent(
            id=row.id, event_type=row.event_type, actor_user_id=row.actor_user_id,
            created_at=utc(row.created_at), result_sha256=row.event_data["result_sha256"],
        ) for row in rows)
