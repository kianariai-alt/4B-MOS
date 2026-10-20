"""Experimental PR44 CoreAdapter: gate existing record observations with series quality.

This never invents an observation/source, authenticates a review, or changes the
strict unified v1 contract. Binding and clinical-field presence are trusted caller
inputs. The integration engine remains responsible for source review authority.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import re

from backend.app.decision_intelligence import (
    ClinicalInput, EvaluationRequirements, ImagingInput, RuleBasedDecisionAdapter, ValidationRequest,
)

from .models import canonical_digest
from .series import SERIES_SCHEMA_VERSION, StudyAssessment


INTEGRATION_REFERENCE_COMMIT = "abb60d24f79efe498a19faaa9d7bc16967061ef7"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z")


@dataclass(frozen=True)
class ReportSeriesBinding:
    """Server-owned association, never patient-identity verification."""

    report_id: str
    report_version: int
    report_content_sha256: str
    clinical_context_sha256: str
    series_sha256: str

    def __post_init__(self):
        if (type(self.report_id) is not str or not _ID.fullmatch(self.report_id)
                or type(self.report_version) is not int or self.report_version < 1
                or any(type(value) is not str or not _SHA.fullmatch(value) for value in
                       (self.report_content_sha256, self.clinical_context_sha256, self.series_sha256))):
            raise ValueError("Invalid report-series binding.")


class GatedImagingRecordAdapter:
    """One classic volume bound to one authoritative report; no v1 DICOM lineage claim."""

    def __init__(self, *, study: StudyAssessment, binding: ReportSeriesBinding,
                 clinical: ClinicalInput, contract=None, clock=None):
        if type(study) is not StudyAssessment or type(binding) is not ReportSeriesBinding:
            raise ValueError("A typed study assessment and report binding are required.")
        if contract is None:
            try:
                from backend.app.schemas import clinical_integration as contract
            except ImportError:
                raise RuntimeError("Unified integration v1 dependency is unavailable.") from None
        if getattr(contract, "CONTRACT_VERSION", None) != "1.0.0":
            raise ValueError("Unsupported integration contract version.")
        self.study, self.binding, self.clinical = study, binding, clinical
        self.contract, self.clock = contract, clock or (lambda: datetime.now(timezone.utc))

    def validation(self):
        series = self.study.series[0] if len(self.study.series) == 1 else None
        issues = set(self.study.issues)
        if series is None:
            issues.add("exactly_one_series_required")
        else:
            issues.update(series.issues)
            if series.sha256 != self.binding.series_sha256:
                issues.add("series_binding_mismatch")
            if series.completeness != "expected_manifest_matched":
                issues.add("expected_inventory_required")
        imaging = ImagingInput(
            metadata_status="valid" if self.study.status == "valid" and not issues else "incomplete",
            metadata_sha256=series.sha256 if series else canonical_digest(self.study.to_dict()),
            metadata_schema_version=SERIES_SCHEMA_VERSION,
            modality=series.modality if series else None,
            body_region=series.body_region if series else None,
            laterality=series.laterality if series else None,
            study_reference=series.study_reference if series else None,
            series_reference=series.series_reference if series else None,
            # This is series scope. A first slice is not a synthetic aggregate SOP.
            instance_reference=None,
            technical_fields=series.common_technical_fields if series else (),
            issue_codes=tuple(sorted(issues)),
        )
        requirements = EvaluationRequirements(
            policy_version="series-record-gate-v1", metadata_schema_version=SERIES_SCHEMA_VERSION,
            required_imaging_fields=("modality", "study_reference", "series_reference", "body_region", "laterality"),
            required_technical_fields=("rows", "columns", "pixel_spacing", "image_orientation_patient"),
        )
        return RuleBasedDecisionAdapter(requirements).evaluate(ValidationRequest(self.clinical, imaging))

    def current_version(self):
        return self.contract.ComponentVersion(
            component_id="4b-imaging-series-record-gate", version="1.0.0", kind="adapter",
            artifact_sha256=canonical_digest({
                "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "policy": "series-record-gate-v1", "unified_contract": "1.0.0",
                "reference_commit": INTEGRATION_REFERENCE_COMMIT,
            }),
        )

    def collect(self, context):
        context = self.contract.CoreInput.model_validate(context.model_dump(mode="json"))
        now = self.clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("An aware evaluation clock is required.")
        finding_values, invalid = [], False
        matching_context = context.clinical_context_sha256 == self.binding.clinical_context_sha256
        for item in context.observations:
            if item.observation.category != "imaging":
                continue
            source = item.source
            if (source.record_type != "paraclinical_report" or source.record_id != self.binding.report_id
                    or source.version != self.binding.report_version
                    or source.content_sha256 != self.binding.report_content_sha256):
                invalid = True
                continue
            finding_values.append(self.contract.CoreFinding(
                finding_id=canonical_digest(source.model_dump(mode="json")),
                source=source.model_copy(deep=True), observation=item.observation.model_copy(deep=True), origin="record",
            ))
        ready = self.validation().status == "data_ready" and matching_context and not invalid
        return self.contract.CoreOutput(
            core="imaging", visit_id=context.visit_id,
            clinical_context_sha256=context.clinical_context_sha256,
            component=self.current_version(), generated_at=now, valid_until=now + timedelta(hours=1),
            status="unavailable" if not ready else "available" if finding_values else "missing",
            findings=tuple(sorted(finding_values, key=lambda x:x.finding_id)) if ready else (),
        )
