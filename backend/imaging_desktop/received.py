"""Keep received content separate from optional volume processing."""

from dataclasses import dataclass, field
import hashlib

from backend.app.imaging_intelligence.intake import ArtifactInventory, IntakeError, inventory, MAX_BYTES
from .sources import ImportFailure, check_cancel, unpack


@dataclass(frozen=True)
class ReceivedArtifact:
    payload: bytes = field(repr=False)
    inventory: ArtifactInventory
    catalog: object = field(default=None, repr=False)
    processing_code: str = "processor_required"

    def report(self):
        from backend.app.decision_intelligence import ClinicalInput, EvaluationRequirements, ImagingInput, RuleBasedDecisionAdapter, ValidationRequest
        checks = []
        if self.catalog is not None:
            for series in self.catalog.series:
                assessment = series.assessment
                image = ImagingInput(
                    metadata_status=assessment.status, metadata_sha256=assessment.sha256,
                    metadata_schema_version=assessment.schema_version, modality=assessment.modality,
                    body_region=assessment.body_region, laterality=assessment.laterality,
                    study_reference=assessment.study_reference, series_reference=assessment.series_reference,
                    technical_fields=assessment.common_technical_fields,
                    issue_codes=tuple(sorted(set(series.issues) | {"acquisition_completeness_not_established"})),
                )
                requirements = EvaluationRequirements(
                    policy_version="desktop-received-series-v1", metadata_schema_version=assessment.schema_version,
                    required_imaging_fields=("modality", "study_reference", "series_reference"),
                )
                validation = RuleBasedDecisionAdapter(requirements).evaluate(ValidationRequest(ClinicalInput(), image))
                checks.append(validation.to_dict())
        return {"inventory": self.inventory.to_dict(), "processing_code": self.processing_code,
                "technical_validations": checks, "clinical_findings": [], "is_diagnosis": False,
                "report_scope": "intake_and_data_quality_only"}


def receive(raw, *, cancel=None):
    check_cancel(cancel)
    try:
        assessment = inventory(raw)
    except IntakeError as error:
        if type(raw) is not bytes or not raw or len(raw) > MAX_BYTES:
            raise
        assessment = ArtifactInventory("uninspected", len(raw), hashlib.sha256(raw).hexdigest(), issues=(str(error),))
        return ReceivedArtifact(raw, assessment, processing_code="quarantined_invalid_archive")
    if assessment.kind == "html":
        return ReceivedArtifact(raw, assessment, processing_code="portal_page")
    if assessment.kind == "dicom" or (assessment.kind == "zip" and dict(assessment.member_kinds).get("dicom")):
        from .volume import scan
        try:
            catalog = scan(unpack(raw, cancel=cancel), cancel=cancel)
            return ReceivedArtifact(raw, assessment, catalog, "volume_catalog_ready")
        except ImportFailure as error:
            if str(error) == "cancelled":
                raise
            return ReceivedArtifact(raw, assessment, processing_code=str(error))
    return ReceivedArtifact(raw, assessment)
