"""Deterministic composition, with no diagnostic or treatment inference."""

from datetime import datetime, timedelta, timezone
from itertools import combinations
from typing import Mapping

from pydantic import ValidationError

from backend.app.schemas.clinical_integration import (
    ClinicalAssessmentReference, ClinicalEvidenceReference, ComponentVersion, CoreInput, CoreOutput,
    DecisionSupportResult, ImagingStudyReference, IntegratedFinding,
    IntegrationIssue, KnowledgeReference, PatientReference, PhysicianApproval,
    Provenance, VisitReference,
)
from backend.app.services.clinical_integration.ports import CoreAdapter
from backend.app.services.session_finalization import evidence_digest

ENGINE_VERSION = "clinical-integration-1.1.0"
CORE_NAMES = ("orthopedic", "imaging")
MAX_RUN_AGE = timedelta(hours=24)  # Administrative review window, not a clinical age rule.


def digest_model(value) -> str:
    return evidence_digest(value.model_dump(mode="json"))


def _unavailable_version(core: str) -> ComponentVersion:
    return ComponentVersion(
        component_id=f"{core}-unavailable", version="unknown", kind="adapter",
        artifact_sha256=evidence_digest({"core": core, "unavailable": True}),
    )


def collect_cores(
    context: CoreInput, adapters: Mapping[str, CoreAdapter], *, now: datetime,
) -> tuple[tuple[CoreOutput, ...], tuple[IntegrationIssue, ...]]:
    outputs, issues = [], []
    for name in CORE_NAMES:
        component = _unavailable_version(name)
        try:
            adapter = adapters[name]
            component = ComponentVersion.model_validate(adapter.current_version().model_dump())
            # Give each producer an independent copy, so mutation cannot leak
            # across cores or change the authoritative source snapshot.
            producer_input = context.model_copy(deep=True, update={"observations": tuple(
                item.model_copy(deep=True) for item in context.observations
                if (item.observation.category == "imaging") == (name == "imaging")
            )})
            output = CoreOutput.model_validate(adapter.collect(producer_input).model_dump(mode="json"))
            if (output.core != name or output.visit_id != context.visit_id
                    or output.clinical_context_sha256 != context.clinical_context_sha256
                    or output.component != component):
                raise ValueError("Core envelope does not match the trusted invocation.")
            if output.generated_at > now + timedelta(minutes=5):
                raise ValueError("Core timestamp is in the future.")
            if output.valid_until <= now:
                issues.append(IntegrationIssue(code="expired_core_output", core=name, severity="blocking"))
            elif now - output.generated_at > MAX_RUN_AGE:
                issues.append(IntegrationIssue(code="expired_core_output", core=name, severity="blocking"))
                output = None
        except (ValidationError, ValueError, TypeError, AttributeError):
            issues.append(IntegrationIssue(code="invalid_core_output", core=name, severity="blocking"))
            output = None
        except Exception:
            # A plugin boundary may fail in arbitrary ways. Never expose its
            # exception text, patient details, image URLs, or access tokens.
            issues.append(IntegrationIssue(code="core_unavailable", core=name, severity="blocking"))
            output = None
        if output is None:
            output = CoreOutput(
                core=name, visit_id=context.visit_id,
                clinical_context_sha256=context.clinical_context_sha256,
                component=component, generated_at=now, valid_until=now + MAX_RUN_AGE,
                status="unavailable",
            )
        if output.status != "available":
            issues.append(IntegrationIssue(code=f"core_{output.status}", core=name, severity="blocking"))
        elif not output.findings:
            issues.append(IntegrationIssue(code="core_has_no_findings", core=name, severity="blocking"))
        outputs.append(output)
    return tuple(outputs), tuple(issues)


def assemble_result(
    *, patient_id: str, visit: VisitReference, context: CoreInput,
    assessment: ClinicalAssessmentReference | None,
    studies: tuple[ImagingStudyReference, ...],
    approvals: Mapping[str, PhysicianApproval],
    cores: tuple[CoreOutput, ...], knowledge: tuple[KnowledgeReference, ...],
    copilot_sha256: str, safety_rule_set_sha256: str,
    issues: tuple[IntegrationIssue, ...], now: datetime,
    evidence_briefs: tuple[ClinicalEvidenceReference, ...] = (),
    dependency_valid_until: tuple[datetime, ...] = (),
) -> DecisionSupportResult:
    """Accept exact reviewed source values; quarantine every model assertion.

    `approvals` is built only from server-owned finalized records, never from a
    producer's review claims. There is intentionally no model auto-approval.
    """
    confirmed, pending = [], []
    problems = list(issues)
    sources = {digest_model(item.source): item for item in context.observations}
    seen_sources: set[tuple[str, str]] = set()
    for core in cores:
        if core.status != "available" or core.valid_until <= now:
            continue
        for item in core.findings:
            key = digest_model(item.source)
            source = sources.get(key)
            expected_core = "imaging" if item.observation.category == "imaging" else "orthopedic"
            source_core = (
                "imaging" if source and source.observation.category == "imaging" else "orthopedic"
            )
            if source is None or expected_core != core.core or source_core != core.core:
                problems.append(IntegrationIssue(
                    code="invalid_finding_source", core=core.core, severity="blocking",
                    finding_ids=(item.finding_id,),
                ))
                continue
            if item.origin == "record" and item.observation != source.observation:
                problems.append(IntegrationIssue(
                    code="record_value_mismatch", core=core.core, severity="blocking",
                    finding_ids=(item.finding_id,),
                ))
                continue
            if (core.core, key) in seen_sources:
                problems.append(IntegrationIssue(
                    code="duplicate_finding_source", core=core.core, severity="blocking",
                    finding_ids=(item.finding_id,),
                ))
                continue
            seen_sources.add((core.core, key))
            approval = approvals.get(key) if item.origin == "record" else None
            is_confirmed = approval is not None
            finding = IntegratedFinding(
                core=core.core, finding=item, approval=approval,
                review_status=("confirmed_source" if is_confirmed else
                               "unreviewed_model" if item.origin == "model" else "unreviewed_source"),
                usable_as_confirmed_finding=is_confirmed,
            )
            (confirmed if is_confirmed else pending).append(finding)
            if not is_confirmed:
                problems.append(IntegrationIssue(
                    code="finding_requires_physician_review", core=core.core,
                    severity="blocking", finding_ids=(item.finding_id,),
                ))

    # Producers may only return a subset of their input. Preserve every omitted
    # source reference explicitly, including omissions caused by invalid values;
    # partial composition must never appear ready for summary approval.
    for name in CORE_NAMES:
        omitted = tuple(item.source for item in context.observations
                        if ((item.observation.category == "imaging") == (name == "imaging")
                            and (name, digest_model(item.source)) not in seen_sources))
        if omitted:
            problems.append(IntegrationIssue(
                code="incomplete_core_coverage", core=name, severity="blocking",
                source_references=omitted,
            ))

    # A narrow data-consistency check, not medical reconciliation: compare only
    # identical terminology/version, body site and typed-value kind across cores.
    for left, right in combinations(confirmed, 2):
        a, b = left.finding.observation, right.finding.observation
        attributes = ("code_system", "code_system_uri", "code_system_version", "code", "body_site", "value_type")
        if left.core == right.core or not a.body_site:
            continue
        if (all(getattr(a, field) == getattr(b, field) for field in attributes)
                and a.value_type in {"boolean", "coded", "integer"}
                and (a.boolean_value, a.coded_system, a.coded_value, a.integer_value)
                != (b.boolean_value, b.coded_system, b.coded_value, b.integer_value)):
            problems.append(IntegrationIssue(
                code="discordant_values_for_same_code_and_site", severity="blocking",
                finding_ids=(left.finding.finding_id, right.finding.finding_id),
            ))
    if assessment is None:
        problems.append(IntegrationIssue(code="final_clinical_assessment_missing", severity="blocking"))
    if visit.status == "cancelled":
        problems.append(IntegrationIssue(code="visit_cancelled", severity="blocking"))
    if not knowledge:
        problems.append(IntegrationIssue(code="no_knowledge_selected", severity="warning"))
    valid_until = min([now + MAX_RUN_AGE, *dependency_valid_until] + [core.valid_until for core in cores])
    return DecisionSupportResult(
        patient=PatientReference(patient_id=patient_id), visit=visit, assessment=assessment,
        imaging_studies=studies,
        raw_record_references=tuple(item.source for item in context.observations),
        confirmed_findings=tuple(confirmed), unreviewed_findings=tuple(pending),
        cores=cores, knowledge=knowledge, evidence_briefs=evidence_briefs, issues=tuple(problems),
        provenance=Provenance(
            engine_version=ENGINE_VERSION, clinical_context_sha256=context.clinical_context_sha256,
            copilot_snapshot_sha256=copilot_sha256, safety_rule_set_sha256=safety_rule_set_sha256,
            components=tuple(core.component for core in cores),
            core_output_sha256s=tuple(digest_model(core) for core in cores),
        ),
        generated_at=now.astimezone(timezone.utc), valid_until=valid_until,
        workflow_state=("blocked" if any(p.severity == "blocking" for p in problems)
                        else "awaiting_physician_review"),
    )
