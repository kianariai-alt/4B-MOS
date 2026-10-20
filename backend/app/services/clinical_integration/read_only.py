"""Live GET composition; no writes, persisted runs, review claims or inference."""

from datetime import datetime, timezone

from backend.app.models.user import User
from backend.app.schemas.clinical_integration import ClinicalEvidenceReference, IntegrationIssue, VisitReference
from backend.app.schemas.clinical_intelligence import (
    ClinicalCaseReference, ClinicalSafetyStatus, ImagingReviewReference,
    IntegratedClinicalSnapshot, ProvenanceManifest, SafetyAlertReference, SafetyEvaluationReference,
)
from backend.app.services.clinical_context import ClinicalContextService
from backend.app.services.clinical_integration.adapters import approved_knowledge, local_adapters, source_bundle, utc
from backend.app.services.clinical_integration.decision import collect_decision
from backend.app.services.clinical_integration.engine import assemble_result, collect_cores
from backend.app.services.clinical_integration.service import _require_actor, _visit, _rules_hash, IntegrationConflictError
from backend.app.services.physician_copilot import PhysicianCopilotService
from backend.app.services.session_finalization import evidence_digest


def imaging_review_inventory(db, visit_id):
    result = []
    for report in ClinicalContextService.list_reports(db, visit_id):
        if report.category != "imaging":
            continue
        reviewer = db.get(User, report.finalized_by_user_id) if report.finalized_by_user_id else None
        verified = (report.status == "final" and reviewer is not None
                    and reviewer.role == "physician" and report.finalized_at is not None)
        status = ("verified" if verified else "rejected" if report.status == "entered_in_error"
                  else "invalid" if report.status == "superseded" else "unverified")
        result.append(ImagingReviewReference(
            report_id=report.id, version=report.version, content_sha256=report.content_sha256,
            source_status=report.status, review_status=status,
            physician_user_id=reviewer.id if verified else None,
            reviewed_at=utc(report.finalized_at) if verified else None,
            eligible_as_current_source=bool(verified),
        ))
    return tuple(sorted(result, key=lambda item: (item.report_id, item.version)))


def safety_status(copilot, rules_hash):
    inbox = copilot.safety_inbox
    evaluation = inbox.evaluation
    if evaluation is None:
        return ClinicalSafetyStatus(status="missing")
    status = evaluation.outcome
    if inbox.evaluation_matches_current_context is not True or evaluation.rule_set_sha256 != rules_hash:
        status = "stale"
    elif copilot.open_escalations:
        status = "alerts_present"
    return ClinicalSafetyStatus(
        status=status, evaluation=SafetyEvaluationReference(
            evaluation_id=evaluation.id, result_sha256=evaluation.result_sha256,
            clinical_context_sha256=evaluation.clinical_context_sha256,
            rule_set_sha256=evaluation.rule_set_sha256, engine_version=evaluation.engine_version,
            created_at=utc(evaluation.created_at),
        ),
        alerts=tuple(SafetyAlertReference(
            finding_id=item.finding.id, rule_id=item.finding.rule_id,
            rule_version=item.finding.rule_version, rule_content_sha256=item.finding.rule_content_sha256,
            severity=item.finding.severity, required_action=item.finding.action,
            review_status=item.timeline.review_status,
        ) for item in inbox.findings),
        evaluated_rule_count=evaluation.evaluated_rule_count,
        open_escalation_count=len(copilot.open_escalations),
    )


def semantic_core(core):
    value = core.model_dump(mode="json")
    # Passthrough adapters re-read identical finalized records on every GET.
    # Model timestamps are dependencies and remain part of their digest.
    if core.component.kind == "adapter":
        value.pop("generated_at")
        value.pop("valid_until")
    return value


def snapshot_digest(snapshot):
    """Hash a documented semantic projection, never a signature.

    Ignore GET observation time, the composition window, and passthrough-adapter
    read times. Preserve model times, all values, review/validity states, issue
    codes, dependencies and hashes. Raw core hashes are replaced with their
    semantic equivalents so repeated reads of unchanged records are stable.
    """
    value = snapshot.model_dump(mode="json", exclude={"snapshot_sha256", "observed_at"})
    value["result"].pop("generated_at")
    value["result"].pop("valid_until")
    value["result"]["cores"] = [semantic_core(core) for core in snapshot.result.cores]
    value["result"]["provenance"]["core_output_sha256s"] = list(
        snapshot.provenance_manifest.core_semantic_sha256s,
    )
    return evidence_digest(value)


def get_clinical_intelligence(db, visit_id, *, actor, adapters=None, decision_adapter=None):
    _require_actor(db, actor)
    visit = _visit(db, visit_id)
    adapters = local_adapters() if adapters is None else adapters
    now = datetime.now(timezone.utc)
    copilot = PhysicianCopilotService.get_snapshot(db, visit_id)
    context_hash = copilot.manifest.clinical_context_sha256
    rules_hash = _rules_hash(db, now)
    bundle = source_bundle(db, copilot.clinical_context, context_hash)
    images = imaging_review_inventory(db, visit_id)
    cores, core_issues = collect_cores(bundle.core_input, adapters, now=now)
    issues = list(core_issues + bundle.issues)

    # Reuse clinician-selected evidence only; do not imply relevance by listing
    # every fact in a domain. Revalidate each historical selection in Registry.
    ids = sorted({fact_id for brief in copilot.current_context_evidence_briefs
                  for fact_id in brief.knowledge_fact_ids})
    knowledge = []
    if len(ids) > 50:
        issues.append(IntegrationIssue(code="knowledge_reference_limit_exceeded", severity="blocking"))
    for fact_id in ids[:50]:
        try:
            knowledge.extend(approved_knowledge(db, (fact_id,), as_of=now.date()))
        except (ValueError, LookupError):
            issues.append(IntegrationIssue(code="selected_knowledge_no_longer_valid", severity="blocking"))
    knowledge = tuple(knowledge)
    safety = safety_status(copilot, rules_hash)
    safety_issues = {
        "missing": ("safety_evaluation_missing", "blocking"),
        "stale": ("safety_evaluation_stale", "blocking"),
        "alerts_present": ("safety_alerts_require_review", "blocking"),
        "no_active_rules": ("no_active_safety_rules", "warning"),
    }
    if safety.status in safety_issues:
        code, severity = safety_issues[safety.status]
        issues.append(IntegrationIssue(code=code, severity=severity))
    decision = collect_decision(bundle.core_input, decision_adapter, now=now, approved_knowledge=knowledge)
    if decision.status != "missing":
        issues.extend(IntegrationIssue(code=code, severity="blocking") for code in decision.issue_codes)
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
            context_matches=(brief.clinical_context_sha256 == context_hash),
        ) for brief in copilot.evidence_briefs),
    )
    # Detect source/Registry/Safety/review changes during collection. A failing
    # dependency is returned as a controlled HTTP error, never apparent success.
    db.expire_all()
    verified_at = datetime.now(timezone.utc)
    current = PhysicianCopilotService.get_snapshot(db, visit_id)
    current_visit = _visit(db, visit_id)
    current_knowledge = approved_knowledge(db, tuple(item.fact_id for item in knowledge), as_of=verified_at.date())
    if (current.snapshot_sha256 != copilot.snapshot_sha256 or _rules_hash(db, verified_at) != rules_hash
            or safety_status(current, rules_hash) != safety
            or current_visit.status != result.visit.status or current_visit.patient_id != result.patient.patient_id
            or imaging_review_inventory(db, visit_id) != images or current_knowledge != knowledge
            or source_bundle(db, current.clinical_context, context_hash).approvals != bundle.approvals):
        raise IntegrationConflictError("Dependencies changed during read-only composition.")
    if any(core.status == "available" and now < core.valid_until <= verified_at for core in cores):
        raise IntegrationConflictError("Core output expired during composition.")
    if decision.result is not None and decision.result.valid_until <= verified_at:
        raise IntegrationConflictError("Decision output expired during composition.")
    _require_actor(db, actor)
    for core in cores:
        try:
            changed = adapters[core.core].current_version() != core.component
        except Exception:
            changed = core.status != "unavailable"
        if changed and core.status != "unavailable":
            raise IntegrationConflictError("Core deployment changed during composition.")
    if decision.component is not None and decision_adapter is not None:
        try:
            changed = decision_adapter.current_version() != decision.component
        except Exception as error:
            raise IntegrationConflictError("Decision deployment is unverifiable.") from error
        if changed:
            raise IntegrationConflictError("Decision deployment changed during composition.")
    return make_snapshot(result, images=images, decision=decision, safety=safety, now=now)


def make_snapshot(result, *, images, decision, safety, now):
    """Pure output adapter, shared with the database-free synthetic demo."""
    manifest_data = dict(
        engine_version=result.provenance.engine_version,
        clinical_context_sha256=result.provenance.clinical_context_sha256,
        copilot_snapshot_sha256=result.provenance.copilot_snapshot_sha256,
        safety_rule_set_sha256=result.provenance.safety_rule_set_sha256,
        safety_evaluation_sha256=safety.evaluation.result_sha256 if safety.evaluation else None,
        components=result.provenance.components,
        core_semantic_sha256s=tuple(evidence_digest(semantic_core(core)) for core in result.cores),
        knowledge_sha256s=tuple(item.content_sha256 for item in result.knowledge),
        imaging_review_sha256=evidence_digest({"reviews": [item.model_dump(mode="json") for item in images]}),
        decision_reference_sha256=evidence_digest(decision.model_dump(mode="json")),
    )
    serializable = {**manifest_data, "components": [item.model_dump(mode="json") for item in manifest_data["components"]]}
    manifest = ProvenanceManifest(**manifest_data, manifest_sha256=evidence_digest(serializable))
    status = ("imaging_unavailable" if not result.imaging_studies else
              "degraded" if result.workflow_state == "blocked" else "awaiting_physician_review")
    snapshot = IntegratedClinicalSnapshot(
        status=status, clinical_context_reference=ClinicalCaseReference(
            visit_id=result.visit.visit_id, clinical_context_sha256=result.provenance.clinical_context_sha256,
        ), result=result, imaging_review=images, decision_model_reference=decision,
        safety_status=safety,
        review_requirements=tuple(sorted({item.code for item in result.issues if item.severity == "blocking"})),
        data_limitations=tuple(sorted({item.code for item in result.issues} | {
            "dicom_identity_not_verified", "knowledge_applicability_not_assessed",
            "no_automatic_diagnosis_or_treatment", *decision.issue_codes,
        })),
        provenance_manifest=manifest, observed_at=now, snapshot_sha256="0" * 64,
    )
    return snapshot.model_copy(update={"snapshot_sha256": snapshot_digest(snapshot)})
