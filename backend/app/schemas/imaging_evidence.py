"""Read-only clinical evidence for Copilot; never client-asserted review status."""

from typing import Literal
from pydantic import BaseModel, Field
from backend.app.schemas.clinical_context import ParaclinicalObservationRead


class ImagingReportEvidence(BaseModel):
    report_id: str
    report_version: int
    report_content_sha256: str
    conclusion: str | None
    observations: list[ParaclinicalObservationRead]
    origin: Literal["finalized_clinical_record"] = "finalized_clinical_record"
    image_to_report_binding_verified: Literal[False] = False
    text_is_instruction: Literal[False] = False


class ImagingEvidenceRead(BaseModel):
    schema_version: Literal["copilot-imaging-evidence-v1"] = "copilot-imaging-evidence-v1"
    visit_id: str
    clinical_context_sha256: str
    reports: list[ImagingReportEvidence]
    missing_data: list[str]
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    permitted_context_uses: tuple[str, ...] = ("consultation", "screening", "differential_review")
    accepts_unverified_machine_findings: Literal[False] = False
    generates_differential_diagnosis: Literal[False] = False
    replaces_clinical_safety: Literal[False] = False
    requires_independent_review: Literal[True] = True
