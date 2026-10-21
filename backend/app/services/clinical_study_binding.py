"""Append-only physician-attested study links, separate from image interpretation.

Producer digests and quality are assertions. No trusted DICOM ingestion is
registered here; an association review cannot authenticate a scan or a model.
"""

from datetime import datetime, timedelta, timezone
import uuid

from pydantic import ValidationError
from sqlalchemy import select

from backend.app.db.clinical_record_transactions import clinical_record_write
from backend.app.models.clinical_study_binding import ClinicalStudyBinding, ClinicalStudyBindingReview
from backend.app.models.user import User
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.schemas.clinical_integration import IntegrationIssue
from backend.app.schemas.clinical_study_binding import (
    BindingSnapshot, StudyBindingContent, StudyBindingCreate, StudyBindingInventory,
    StudyBindingRead, StudyBindingReview, StudyBindingReviewCreate,
)
from backend.app.services.audit_context import actor_data
from backend.app.services.clinical_context import ClinicalContextService
from backend.app.services.clinical_integration.adapters import utc
from backend.app.services.clinical_integration.service import (
    IntegrationConflictError, IntegrationIntegrityError, IntegrationNotFoundError,
    _require_actor, _visit,
)
from backend.app.services.physician_copilot import PhysicianCopilotService
from backend.app.services.session_finalization import evidence_digest


def utcnow():
    return datetime.now(timezone.utc)


def _digest(value):
    return evidence_digest(value.model_dump(mode="json"))


def _request_digest(payload, actor_id):
    return evidence_digest({"request": payload.model_dump(mode="json"), "actor_user_id": actor_id})


def _verify_binding(row):
    try:
        binding = BindingSnapshot.model_validate(row.payload)
        request = StudyBindingCreate(
            **binding.model_dump(include=set(StudyBindingContent.model_fields)),
            request_key=row.request_key,
            expected_previous_binding_sha256=binding.previous_binding_sha256,
        )
        if (_digest(binding) != row.sha256 or binding.id != row.id
                or binding.visit_id != row.visit_id or binding.report_id != row.report_id
                or binding.report_key != row.report_key or binding.revision != row.revision
                or binding.created_by_user_id != row.created_by_user_id
                or binding.created_at != utc(row.created_at)
                or binding.request_sha256 != row.request_sha256
                or _request_digest(request, row.created_by_user_id) != row.request_sha256):
            raise ValueError("Binding metadata mismatch.")
        return binding
    except (ValidationError, ValueError, TypeError) as error:
        raise IntegrationIntegrityError("Study binding failed its integrity check.") from error


def _rows(db, visit_id):
    rows = db.scalars(select(ClinicalStudyBinding).where(
        ClinicalStudyBinding.visit_id == visit_id,
    ).order_by(ClinicalStudyBinding.report_key, ClinicalStudyBinding.revision)).all()
    verified, latest = {}, {}
    for row in rows:
        binding = _verify_binding(row)
        previous = latest.get(row.report_key)
        if (binding.revision != (previous.revision + 1 if previous else 1)
                or binding.previous_binding_sha256 != (previous.sha256 if previous else None)):
            raise IntegrationIntegrityError("Study binding history is incomplete.")
        verified[row.id] = binding
        latest[row.report_key] = row
    return rows, verified, latest


def _reviews(db, row):
    rows = db.scalars(select(ClinicalStudyBindingReview).where(
        ClinicalStudyBindingReview.binding_id == row.id,
    ).order_by(ClinicalStudyBindingReview.sequence)).all()
    result, previous_hash, previous_action = [], None, None
    for index, item in enumerate(rows, 1):
        try:
            review = StudyBindingReview.model_validate(item.payload)
            if (_digest(review) != item.sha256 or review.id != item.id
                    or review.binding_id != row.id or review.visit_id != row.visit_id
                    or review.binding_sha256 != row.sha256 or review.request_key != item.request_key
                    or review.sequence != index or item.sequence != index
                    or review.previous_review_sha256 != previous_hash
                    or review.physician_user_id != item.physician_user_id
                    or review.reviewed_at != utc(item.created_at)
                    or (previous_action is not None
                        and (previous_action != "confirm" or review.action != "invalidate"))):
                raise ValueError("Review history mismatch.")
        except (ValidationError, ValueError, TypeError) as error:
            raise IntegrationIntegrityError("Study binding review failed its integrity check.") from error
        result.append(review)
        previous_hash, previous_action = item.sha256, review.action
    return tuple(result), previous_hash


def _read(db, row, binding, *, latest, reports, context_sha256, now):
    reviews, last_hash = _reviews(db, row)
    status = {"confirm": "verified", "reject": "rejected", "invalidate": "invalid"}.get(
        reviews[-1].action if reviews else None, "unverified",
    )
    reasons = []
    if latest[binding.report_key].id != binding.id:
        reasons.append("study_binding_superseded")
    if binding.clinical_context_sha256 != context_sha256:
        reasons.append("clinical_context_changed")
    report = reports.get(binding.report_id)
    if report is None or report.visit_id != binding.visit_id or report.category != "imaging":
        reasons.append("imaging_report_unavailable")
    elif (report.version != binding.report_version or report.content_sha256 != binding.report_content_sha256
          or report.report_key != binding.report_key):
        reasons.append("imaging_report_changed")
    elif report.status != "final":
        reasons.append("imaging_report_not_final")
    else:
        finalizer = db.get(User, report.finalized_by_user_id) if report.finalized_by_user_id else None
        if finalizer is None or finalizer.role != "physician" or report.finalized_at is None:
            reasons.append("imaging_report_not_physician_finalized")
    if (binding.source_valid_until <= now or now - binding.source_generated_at > timedelta(hours=24)):
        reasons.append("study_binding_source_expired")
    if binding.source_generated_at > now + timedelta(minutes=5):
        reasons.append("study_binding_source_in_future")
    return StudyBindingRead(
        binding=binding, binding_sha256=row.sha256, reviews=reviews,
        review_status=status, freshness="stale" if reasons else "current",
        invalidation_reasons=tuple(reasons), latest_review_sha256=last_hash,
        eligible_for_contextual_link=(status == "verified" and not reasons
                                     and binding.quality_status == "data_ready"),
    )


def binding_inventory(db, visit_id, *, context_sha256=None, now=None):
    """Internal read projection. Callers own authentication and visit checks.

    One current series association per report stream in v1. A replacement takes
    effect immediately, even while awaiting review; older approvals never revive.
    """
    now = utcnow() if now is None else now
    if context_sha256 is None:
        context_sha256 = PhysicianCopilotService.get_snapshot(db, visit_id).manifest.clinical_context_sha256
    _, verified, latest = _rows(db, visit_id)
    reports = {item.id: item for item in ClinicalContextService.list_reports(db, visit_id)}
    bindings = tuple(_read(db, row, verified[row.id], latest=latest, reports=reports,
                           context_sha256=context_sha256, now=now)
                     for _, row in sorted(latest.items()))
    # Only opaque digests escape into the public provenance manifest. The full
    # inventory (including physician rationale) stays in authenticated responses.
    digest = evidence_digest({"schema_version": "1.0.0", "bindings": [
        {"binding_sha256": item.binding_sha256, "latest_review_sha256": item.latest_review_sha256,
         "review_status": item.review_status, "freshness": item.freshness,
         "invalidation_reasons": item.invalidation_reasons,
         "eligible_for_contextual_link": item.eligible_for_contextual_link}
        for item in bindings
    ]})
    return StudyBindingInventory(bindings=bindings, sha256=digest)


def binding_issues(inventory):
    issues = []
    for item in inventory.bindings:
        if not item.eligible_for_contextual_link:
            code = ("study_binding_stale" if item.freshness == "stale"
                    else f"study_binding_{item.review_status}")
            issues.append(IntegrationIssue(code=code, severity="blocking", core="imaging"))
        if item.binding.quality_status != "data_ready":
            issues.append(IntegrationIssue(code="study_binding_quality_not_ready", severity="blocking", core="imaging"))
    return tuple(issues)


class StudyBindingService:
    @staticmethod
    def list(db, visit_id, *, actor):
        _require_actor(db, actor)
        _visit(db, visit_id)
        observed = binding_inventory(db, visit_id)
        db.expire_all()
        if binding_inventory(db, visit_id).sha256 != observed.sha256:
            raise IntegrationConflictError("Study binding dependencies changed during the read.")
        _require_actor(db, actor)
        return observed

    @staticmethod
    def get(db, visit_id, binding_id, *, actor):
        _require_actor(db, actor)
        _visit(db, visit_id)
        observed = StudyBindingService._get(db, visit_id, binding_id)
        db.expire_all()
        if StudyBindingService._get(db, visit_id, binding_id) != observed:
            raise IntegrationConflictError("Study binding dependencies changed during the read.")
        _require_actor(db, actor)
        return observed

    @staticmethod
    def _get(db, visit_id, binding_id):
        rows, verified, latest = _rows(db, visit_id)
        row = next((item for item in rows if item.id == binding_id), None)
        if row is None:
            raise IntegrationNotFoundError("Study binding was not found for this visit.")
        context = PhysicianCopilotService.get_snapshot(db, visit_id).manifest.clinical_context_sha256
        reports = {item.id: item for item in ClinicalContextService.list_reports(db, visit_id)}
        return _read(db, row, verified[row.id], latest=latest, reports=reports,
                     context_sha256=context, now=utcnow())

    @staticmethod
    @clinical_record_write
    def create(db, visit_id: str, payload: StudyBindingCreate, *, actor):
        actor = _require_actor(db, actor)
        _visit(db, visit_id)
        payload = StudyBindingCreate.model_validate(payload.model_dump(mode="json"))
        request_hash = _request_digest(payload, actor.id)
        previous_request = db.scalar(select(ClinicalStudyBinding).where(
            ClinicalStudyBinding.visit_id == visit_id, ClinicalStudyBinding.request_key == payload.request_key,
        ))
        if previous_request is not None:
            if previous_request.request_sha256 != request_hash:
                raise IntegrationConflictError("Binding request key was already used for different inputs or actor.")
            return StudyBindingService.get(db, visit_id, previous_request.id, actor=actor)
        now = utcnow()
        report = ClinicalContextService.get_report(db, payload.report_id)
        if report.visit_id != visit_id or report.category != "imaging":
            raise IntegrationConflictError("The report is not an imaging source of this visit.")
        context = PhysicianCopilotService.get_snapshot(db, visit_id).manifest.clinical_context_sha256
        if (report.version != payload.report_version or report.content_sha256 != payload.report_content_sha256
                or context != payload.clinical_context_sha256):
            raise IntegrationConflictError("Binding source changed; reload before proposing a link.")
        if (payload.source_valid_until <= now or now - payload.source_generated_at > timedelta(hours=24)
                or payload.source_generated_at > now + timedelta(minutes=5)):
            raise IntegrationConflictError("Study metadata is expired or future-dated.")
        _, _, latest = _rows(db, visit_id)
        previous = latest.get(report.report_key)
        if payload.expected_previous_binding_sha256 != (previous.sha256 if previous else None):
            raise IntegrationConflictError("Study binding changed; reload its current revision.")
        binding = BindingSnapshot(
            **payload.model_dump(include=set(StudyBindingContent.model_fields)),
            id=str(uuid.uuid4()), visit_id=visit_id, report_key=report.report_key,
            revision=previous.revision + 1 if previous else 1,
            previous_binding_sha256=previous.sha256 if previous else None,
            request_sha256=request_hash, created_by_user_id=actor.id, created_at=now,
        )
        row = ClinicalStudyBinding(
            id=binding.id, visit_id=visit_id, report_id=report.id, report_key=report.report_key,
            revision=binding.revision, request_key=payload.request_key, request_sha256=request_hash,
            created_by_user_id=actor.id, created_at=now, sha256=_digest(binding), payload=binding.model_dump(mode="json"),
        )
        db.add(row)
        db.flush()
        AuditLogRepository.create(
            db, commit=False, entity_type="clinical_study_binding", entity_id=row.id,
            event_type="study_binding_proposed", to_state="unverified",
            event_data={"binding_sha256": row.sha256, "revision": row.revision}, **actor_data(actor),
        )
        return StudyBindingService.get(db, visit_id, row.id, actor=actor)

    @staticmethod
    @clinical_record_write
    def review(db, visit_id: str, binding_id: str, payload: StudyBindingReviewCreate, *, actor):
        actor = _require_actor(db, actor, physician_only=True)
        payload = StudyBindingReviewCreate.model_validate(payload.model_dump(mode="json"))
        current = StudyBindingService.get(db, visit_id, binding_id, actor=actor)
        previous_request = db.scalar(select(ClinicalStudyBindingReview).where(
            ClinicalStudyBindingReview.binding_id == binding_id,
            ClinicalStudyBindingReview.request_key == payload.request_key,
        ))
        if previous_request is not None:
            review = next(item for item in current.reviews if item.id == previous_request.id)
            if (review.physician_user_id != actor.id or review.action != payload.action
                    or review.rationale != payload.rationale or review.binding_sha256 != payload.expected_binding_sha256
                    or review.previous_review_sha256 != payload.expected_previous_review_sha256):
                raise IntegrationConflictError("Review key was already used for a different attestation.")
            return review  # Historical replay is never a fresh approval.
        if (current.binding_sha256 != payload.expected_binding_sha256
                or current.latest_review_sha256 != payload.expected_previous_review_sha256):
            raise IntegrationConflictError("Review must reference the exact current binding and review predecessor.")
        if current.review_status in {"rejected", "invalid"} or (
            current.review_status == "verified" and payload.action != "invalidate"
        ):
            raise IntegrationConflictError("This review is terminal; propose a new binding revision.")
        if payload.action == "confirm" and (
            current.freshness != "current" or current.binding.quality_status != "data_ready"
        ):
            raise IntegrationConflictError("Only current, ready study associations can be confirmed.")
        reviewed_at = utcnow()
        if payload.action == "confirm" and (
            current.binding.source_valid_until <= reviewed_at
            or reviewed_at - current.binding.source_generated_at > timedelta(hours=24)
            or current.binding.source_generated_at > reviewed_at + timedelta(minutes=5)
        ):
            raise IntegrationConflictError("Study metadata expired before the review was recorded.")
        actor = _require_actor(db, actor, physician_only=True)
        review = StudyBindingReview(
            id=str(uuid.uuid4()), binding_id=binding_id, visit_id=visit_id,
            sequence=len(current.reviews) + 1, request_key=payload.request_key,
            binding_sha256=current.binding_sha256, previous_review_sha256=current.latest_review_sha256,
            physician_user_id=actor.id, reviewed_at=reviewed_at, action=payload.action, rationale=payload.rationale,
        )
        row = ClinicalStudyBindingReview(
            id=review.id, binding_id=binding_id, sequence=review.sequence, request_key=payload.request_key,
            physician_user_id=actor.id, created_at=review.reviewed_at, sha256=_digest(review),
            payload=review.model_dump(mode="json"),
        )
        db.add(row)
        db.flush()
        AuditLogRepository.create(
            db, commit=False, entity_type="clinical_study_binding", entity_id=binding_id,
            event_type="study_binding_physician_reviewed", from_state=current.review_status,
            to_state={"confirm": "verified", "reject": "rejected", "invalidate": "invalid"}[review.action],
            event_data={"binding_sha256": current.binding_sha256, "review_sha256": row.sha256,
                        "sequence": row.sequence, "action": review.action}, **actor_data(actor),
        )
        return review
