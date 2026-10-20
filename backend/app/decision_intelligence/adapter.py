"""Pure, deterministic data-readiness rules with no storage or service imports."""

from dataclasses import asdict, dataclass, field, replace
import hashlib
import json
import re
from typing import ClassVar

from .models import (
    ClinicalInput,
    EvaluationRequirements,
    FindingInput,
    FindingProvenance,
    FindingValidation,
    ImagingInput,
    RuleTrace,
    ValidationRequest,
    ValidationResult,
)


CLINICAL_FIELDS = frozenset({
    "assessment_context", "symptom_history", "physical_examination",
    "medical_history", "medication_history", "clinical_review",
})
TECHNICAL_FIELDS = frozenset({
    "rows", "columns", "pixel_spacing", "slice_thickness",
    "bits_allocated", "bits_stored", "high_bit", "pixel_representation",
    "samples_per_pixel", "photometric_interpretation", "transfer_syntax_uid",
    "number_of_frames", "image_orientation_patient", "sop_class_uid",
})
IMAGING_FIELDS = frozenset({
    "modality", "body_region", "laterality", "study_reference",
    "series_reference", "instance_reference",
})
MODALITIES = frozenset({
    "CR", "DX", "CT", "MR", "US", "NM", "PT", "XA", "RF", "MG", "OT",
    "SC", "SR", "SEG", "RTIMAGE", "RTDOSE", "RTSTRUCT", "RTPLAN", "PR",
    "XC", "ES", "ECG", "IO", "PX", "OCT", "OP", "OPT", "SM", "GM",
})
BODY_REGIONS = frozenset({
    "HEAD", "NECK", "CHEST", "ABDOMEN", "PELVIS", "SPINE", "CERVICAL_SPINE",
    "THORACIC_SPINE", "LUMBAR_SPINE", "SHOULDER", "ARM", "ELBOW", "FOREARM",
    "WRIST", "HAND", "HIP", "THIGH", "KNEE", "LEG", "ANKLE", "FOOT",
    "WHOLEBODY", "OTHER", "UNKNOWN",
})
LATERALITIES = frozenset({"L", "R", "B", "U"})
_REFERENCE = re.compile(r"hmac-sha256:[0-9a-f]{64}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_TOKEN = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
_ISSUE_CODE = re.compile(r"[a-zA-Z][a-zA-Z0-9_.-]{0,95}\Z")
_RULES = (
    ("input_schema", "1.0.0"),
    ("clinical_completeness", "1.0.0"),
    ("imaging_completeness", "1.0.0"),
    ("context_consistency", "1.0.0"),
    ("finding_verification", "1.0.0"),
    ("finding_provenance", "1.0.0"),
    ("finding_completeness", "1.0.0"),
)


def _sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def _optional_choice(value: object, choices: frozenset[str]) -> bool:
    return value is None or (type(value) is str and value in choices)


def _matches(value: object, pattern: re.Pattern, *, optional: bool = False) -> bool:
    return (value is None and optional) or (
        type(value) is str and pattern.fullmatch(value) is not None
    )


def _tuple_of_choices(value: object, choices: frozenset[str]) -> bool:
    return (type(value) is tuple and len(value) <= 128
            and all(type(item) is str and item in choices for item in value)
            and len(set(value)) == len(value))


def _tuple_of_tokens(value: object, pattern: re.Pattern) -> bool:
    return (type(value) is tuple and len(value) <= 128
            and all(_matches(item, pattern) for item in value)
            and len(set(value)) == len(value))


def _schema_errors(request: object) -> tuple[str, ...]:
    """Return only static codes, never values from a rejected request."""
    errors: set[str] = set()
    if type(request) is not ValidationRequest:
        return ("invalid_request_type",)
    clinical = request.clinical
    if type(clinical) is not ClinicalInput:
        errors.add("invalid_clinical_schema")
    elif not (
        _tuple_of_choices(clinical.available_fields, CLINICAL_FIELDS)
        and _optional_choice(clinical.body_region, BODY_REGIONS)
        and _optional_choice(clinical.laterality, LATERALITIES)
    ):
        errors.add("invalid_clinical_schema")
    imaging = request.imaging
    if imaging is not None:
        if type(imaging) is not ImagingInput:
            errors.add("invalid_imaging_schema")
        elif not (
            type(imaging.metadata_status) is str
            and imaging.metadata_status in {"valid", "incomplete", "invalid"}
            and _matches(imaging.metadata_sha256, _DIGEST)
            and _matches(imaging.metadata_schema_version, _TOKEN)
            and _optional_choice(imaging.modality, MODALITIES)
            and _optional_choice(imaging.body_region, BODY_REGIONS)
            and _optional_choice(imaging.laterality, LATERALITIES)
            and all(_matches(getattr(imaging, name), _REFERENCE, optional=True)
                    for name in ("study_reference", "series_reference", "instance_reference"))
            and _tuple_of_choices(imaging.technical_fields, TECHNICAL_FIELDS)
            and _tuple_of_tokens(imaging.issue_codes, _ISSUE_CODE)
        ):
            errors.add("invalid_imaging_schema")
        else:
            references = tuple(
                getattr(imaging, name)
                for name in ("study_reference", "series_reference", "instance_reference")
                if getattr(imaging, name) is not None
            )
            if len(references) != len(set(references)):
                errors.add("duplicate_imaging_identity_reference")
    if type(request.findings) is not tuple or len(request.findings) > 256:
        errors.add("invalid_findings_schema")
        return tuple(sorted(errors))
    references: list[str] = []
    for finding in request.findings:
        if type(finding) is not FindingInput:
            errors.add("invalid_finding_schema")
            continue
        if not (
            _matches(finding.finding_reference, _REFERENCE)
            and _matches(finding.finding_code, _TOKEN)
            and type(finding.review_status) is str
            and finding.review_status in {"verified", "unverified", "rejected"}
        ):
            errors.add("invalid_finding_schema")
        else:
            references.append(finding.finding_reference)
        provenance = finding.provenance
        if provenance is not None:
            if type(provenance) is not FindingProvenance or not (
                _matches(provenance.source_instance_reference, _REFERENCE, optional=True)
                and _matches(provenance.source_metadata_sha256, _DIGEST, optional=True)
                and _matches(provenance.source_metadata_schema_version, _TOKEN, optional=True)
                and _matches(provenance.review_record_reference, _REFERENCE, optional=True)
                and _matches(provenance.review_policy_version, _TOKEN, optional=True)
            ):
                errors.add("invalid_provenance_schema")
    if len(set(references)) != len(references):
        errors.add("duplicate_finding_reference")
    return tuple(sorted(errors))


def _validate_requirements(requirements: object) -> None:
    if type(requirements) is not EvaluationRequirements or not (
        _matches(requirements.policy_version, _TOKEN)
        and _matches(requirements.metadata_schema_version, _TOKEN)
        and _matches(requirements.review_policy_version, _TOKEN)
        and _tuple_of_choices(requirements.required_clinical_fields, CLINICAL_FIELDS)
        and _tuple_of_choices(requirements.required_imaging_fields, IMAGING_FIELDS)
        and _tuple_of_choices(requirements.required_technical_fields, TECHNICAL_FIELDS)
        and type(requirements.require_imaging) is bool
        and _optional_choice(requirements.expected_modality, MODALITIES)
        and _optional_choice(requirements.expected_body_region, BODY_REGIONS)
        and _optional_choice(requirements.expected_laterality, LATERALITIES)
        and type(requirements.minimum_verified_findings) is int
        and 0 <= requirements.minimum_verified_findings <= 256
    ):
        raise ValueError("Invalid evaluation requirements")


def _trace(rule_id: str, codes: list[str] | tuple[str, ...], *, applicable: bool = True) -> RuleTrace:
    return RuleTrace(
        rule_id=rule_id, rule_version=dict(_RULES)[rule_id],
        outcome=("failed" if codes else "passed") if applicable else "not_applicable",
        codes=tuple(sorted(set(codes))),
    )


@dataclass(frozen=True)
class RuleBasedDecisionAdapter:
    """No diagnosis, treatment recommendation, clinical scoring, or I/O.

    Trust boundary: verified review status is an assertion from an authenticated
    integration, not proof of a physician's identity. There is no public API.
    Matching versioned provenance is mandatory even when status is verified.
    """

    adapter_id: ClassVar[str] = "4b.data-validation.rules"
    adapter_version: ClassVar[str] = "1.0.0"
    requirements: EvaluationRequirements = field(default_factory=EvaluationRequirements)
    rules_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        _validate_requirements(self.requirements)
        object.__setattr__(self, "rules_sha256", _sha256({
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
            "rules": _RULES,
            "requirements": asdict(self.requirements),
        }))

    def evaluate(self, request: ValidationRequest) -> ValidationResult:
        errors = _schema_errors(request)
        if errors:
            traces = (_trace("input_schema", errors),) + tuple(
                _trace(rule_id, (), applicable=False) for rule_id, _ in _RULES[1:]
            )
            return self._result(
                status="invalid_input", input_sha256=None, traces=traces,
                next_steps=("correct_input_schema",),
            )

        requirements = self.requirements
        input_sha256 = _sha256(asdict(request))
        traces = [_trace("input_schema", ())]
        next_steps: set[str] = set()
        missing_clinical = tuple(sorted(
            set(requirements.required_clinical_fields) - set(request.clinical.available_fields)
        ))
        traces.append(_trace("clinical_completeness", (
            ["missing_required_clinical_fields"] if missing_clinical else []
        )))
        if missing_clinical:
            next_steps.add("complete_required_clinical_data")

        imaging = request.imaging
        imaging_codes: list[str] = []
        missing_imaging: list[str] = []
        if imaging is None:
            if requirements.require_imaging:
                imaging_codes.append("missing_imaging_metadata")
                missing_imaging.append("imaging_metadata")
        else:
            missing_imaging.extend(
                name for name in requirements.required_imaging_fields
                if getattr(imaging, name) is None
            )
            missing_imaging.extend(
                name for name in requirements.required_technical_fields
                if name not in imaging.technical_fields
            )
            if missing_imaging:
                imaging_codes.append("missing_required_imaging_fields")
            if imaging.metadata_status != "valid":
                imaging_codes.append("imaging_metadata_not_valid")
            if imaging.issue_codes:
                imaging_codes.append("unresolved_imaging_metadata_issues")
            if imaging.metadata_schema_version != requirements.metadata_schema_version:
                imaging_codes.append("unsupported_metadata_schema_version")
        traces.append(_trace("imaging_completeness", imaging_codes,
                             applicable=imaging is not None or requirements.require_imaging))
        if imaging_codes:
            next_steps.add("resolve_required_imaging_metadata")

        consistency: list[str] = []
        if imaging is not None:
            for name in ("modality", "body_region", "laterality"):
                expected = getattr(requirements, "expected_" + name)
                observed = getattr(imaging, name)
                if expected is not None and observed != expected:
                    consistency.append(name + "_does_not_match_requirement")
            for name in ("body_region", "laterality"):
                clinical_value = getattr(request.clinical, name)
                imaging_value = getattr(imaging, name)
                if (clinical_value is not None and imaging_value is not None
                        and clinical_value != imaging_value):
                    consistency.append("clinical_imaging_" + name + "_mismatch")
        traces.append(_trace("context_consistency", consistency, applicable=imaging is not None))
        if consistency:
            next_steps.add("reconcile_context_metadata")

        verification_codes: list[str] = []
        provenance_codes: list[str] = []
        eligible: list[str] = []
        blocked: list[str] = []
        finding_checks: list[FindingValidation] = []
        imaging_usable = imaging is not None and not imaging_codes and not consistency
        for finding in request.findings:
            finding_verification_codes: list[str] = []
            finding_provenance_codes: list[str] = []
            verified = finding.review_status == "verified"
            if not verified:
                finding_verification_codes.append("finding_not_verified")
            provenance = finding.provenance
            provenance_ok = False
            if provenance is None:
                finding_provenance_codes.append("missing_finding_provenance")
            elif not all((
                provenance.source_instance_reference,
                provenance.source_metadata_sha256,
                provenance.source_metadata_schema_version,
                provenance.review_record_reference,
                provenance.review_policy_version,
            )):
                finding_provenance_codes.append("incomplete_finding_provenance")
            elif imaging is None:
                finding_provenance_codes.append("finding_source_metadata_unavailable")
            elif (
                provenance.source_instance_reference != imaging.instance_reference
                or provenance.source_metadata_sha256 != imaging.metadata_sha256
                or provenance.source_metadata_schema_version != imaging.metadata_schema_version
            ):
                finding_provenance_codes.append("finding_source_metadata_mismatch")
            elif provenance.review_policy_version != requirements.review_policy_version:
                finding_provenance_codes.append("unsupported_finding_review_policy")
            else:
                provenance_ok = True
            if not imaging_usable:
                finding_provenance_codes.append("finding_source_metadata_not_usable")
            finding_eligible = verified and provenance_ok and imaging_usable
            verification_codes.extend(finding_verification_codes)
            provenance_codes.extend(finding_provenance_codes)
            finding_checks.append(FindingValidation(
                finding_reference=finding.finding_reference, eligible=finding_eligible,
                verification_codes=tuple(sorted(finding_verification_codes)),
                provenance_codes=tuple(sorted(finding_provenance_codes)),
            ))
            if finding_eligible:
                eligible.append(finding.finding_reference)
            else:
                blocked.append(finding.finding_reference)
        traces.extend((
            _trace("finding_verification", verification_codes, applicable=bool(request.findings)),
            _trace("finding_provenance", provenance_codes, applicable=bool(request.findings)),
            _trace("finding_completeness", (
                ["insufficient_verified_findings"]
                if len(eligible) < requirements.minimum_verified_findings else []
            )),
        ))
        if blocked:
            next_steps.add("resolve_finding_review_and_provenance")
        if len(eligible) < requirements.minimum_verified_findings:
            next_steps.add("complete_required_reviewed_finding_data")
        return self._result(
            status="needs_data" if any(t.outcome == "failed" for t in traces) else "data_ready",
            input_sha256=input_sha256, traces=tuple(traces),
            missing_clinical_fields=missing_clinical,
            missing_imaging_fields=tuple(sorted(set(missing_imaging))),
            eligible_finding_references=tuple(sorted(eligible)),
            blocked_finding_references=tuple(sorted(blocked)),
            finding_checks=tuple(sorted(finding_checks, key=lambda item: item.finding_reference)),
            next_steps=tuple(sorted(next_steps)),
        )

    def _result(self, *, status: str, input_sha256: str | None,
                traces: tuple[RuleTrace, ...], **kwargs) -> ValidationResult:
        result = ValidationResult(
            status=status, adapter_id=self.adapter_id, adapter_version=self.adapter_version,
            policy_version=self.requirements.policy_version, input_sha256=input_sha256,
            rules_sha256=self.rules_sha256, result_sha256="", traces=traces, **kwargs,
        )
        payload = asdict(result)
        payload.pop("result_sha256")
        return replace(result, result_sha256=_sha256(payload))
