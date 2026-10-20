"""Explicit local boundary; this does not modify PR44's unified v1 contract."""

from backend.app.decision_intelligence import ImagingInput

from .models import DicomMetadataReport


def to_decision_input(report: DicomMetadataReport) -> ImagingInput:
    return ImagingInput(
        metadata_status=report.status,
        metadata_sha256=report.metadata_sha256,
        metadata_schema_version=report.schema_version,
        modality=report.modality, body_region=report.body_region,
        laterality=report.laterality, study_reference=report.study_reference,
        series_reference=report.series_reference,
        instance_reference=report.instance_reference,
        technical_fields=report.technical.present_fields(),
        issue_codes=tuple(sorted({issue.code for issue in report.issues})),
    )
