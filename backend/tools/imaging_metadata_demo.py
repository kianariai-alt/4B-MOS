"""Run a deterministic local synthetic DICOM → data-validation example.

Usage: python -m backend.tools.imaging_metadata_demo
No URLs, database, existing DICOM files, or real patient inputs are accepted.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage

from backend.app.decision_intelligence import (
    ClinicalInput, EvaluationRequirements, FindingInput, FindingProvenance,
    RuleBasedDecisionAdapter, ValidationRequest,
)
from backend.app.imaging_intelligence.decision_projection import to_decision_input
from backend.app.imaging_intelligence.reader import DicomMetadataReader


SYNTHETIC_REFERENCE_KEY = b"4B-MOS-SYNTHETIC-DEMO-ONLY-KEY-0001"


def write_synthetic_dicom(path: Path, *, incomplete: bool = False) -> None:
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID = MRImageStorage
    meta.MediaStorageSOPInstanceUID = "1.2.826.0.1.3680043.10.543.1003"
    meta.ImplementationClassUID = "1.2.826.0.1.3680043.10.543.1000"
    dataset = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    dataset.SOPClassUID = MRImageStorage
    dataset.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    dataset.StudyInstanceUID = "1.2.826.0.1.3680043.10.543.1001"
    if not incomplete:
        dataset.SeriesInstanceUID = "1.2.826.0.1.3680043.10.543.1002"
    dataset.Modality = "MR"
    dataset.BodyPartExamined = "KNEE"
    dataset.ImageLaterality = "L"
    dataset.PatientName = "SYNTHETIC^DEMO_ONLY"
    dataset.PatientID = "SYNTHETIC-DEMO-ID-NEVER-EXPORT"
    dataset.Rows, dataset.Columns = 4, 4
    dataset.SamplesPerPixel = 1
    dataset.PhotometricInterpretation = "MONOCHROME2"
    dataset.BitsAllocated, dataset.BitsStored = 16, 12
    dataset.HighBit, dataset.PixelRepresentation = 11, 0
    dataset.PixelSpacing = [0.5, 0.5]
    dataset.SliceThickness = 3.0
    dataset.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    dataset.PixelData = b"\0" * 32
    dataset.save_as(path, enforce_file_format=True)


def run_synthetic_demo() -> dict:
    reader = DicomMetadataReader(reference_key=SYNTHETIC_REFERENCE_KEY)
    adapter = RuleBasedDecisionAdapter(EvaluationRequirements(
        required_technical_fields=("rows", "columns", "pixel_spacing"),
        expected_modality="MR", expected_body_region="KNEE", expected_laterality="L",
    ))
    clinical = ClinicalInput(
        available_fields=("assessment_context", "clinical_review"),
        body_region="KNEE", laterality="L",
    )
    scenarios = {}
    with TemporaryDirectory(prefix="4b-imaging-synthetic-") as temporary:
        directory = Path(temporary)
        for name in ("complete", "incomplete", "corrupt"):
            path = directory / (name + ".dcm")
            if name == "corrupt":
                path.write_bytes(b"SYNTHETIC INVALID DICOM")
            else:
                write_synthetic_dicom(path, incomplete=name == "incomplete")
            report = reader.read(path)
            decision = adapter.evaluate(ValidationRequest(clinical, to_decision_input(report)))
            scenarios[name] = {"metadata": report.to_dict(), "validation": decision.to_dict()}
        complete = reader.read(directory / "complete.dcm")
        finding = FindingInput(
            finding_reference="hmac-sha256:" + hashlib.sha256(b"synthetic-finding-only").hexdigest(),
            finding_code="synthetic_observation", review_status="unverified",
            provenance=FindingProvenance(
                source_instance_reference=complete.instance_reference,
                source_metadata_sha256=complete.metadata_sha256,
                source_metadata_schema_version=complete.schema_version,
            ),
        )
        scenarios["unverified_finding"] = {"validation": adapter.evaluate(
            ValidationRequest(clinical, to_decision_input(complete), (finding,))
        ).to_dict()}
    return {
        "synthetic_only": True, "database_accessed": False,
        "is_diagnosis": False, "scenarios": scenarios,
    }


def main() -> None:
    print(json.dumps(run_synthetic_demo(), sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
