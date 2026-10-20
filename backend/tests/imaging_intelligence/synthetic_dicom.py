"""Generated DICOM fixtures only; never read clinical or upstream sample files."""

from __future__ import annotations

from pathlib import Path

import pydicom
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import (
    CTImageStorage,
    ExplicitVRLittleEndian,
    MRImageStorage,
)


SYNTHETIC_STUDY_UID = "1.2.826.0.1.3680043.10.543.1001"
SYNTHETIC_SERIES_UID = "1.2.826.0.1.3680043.10.543.1002"
SYNTHETIC_INSTANCE_UID = "1.2.826.0.1.3680043.10.543.1003"
IDENTIFYING_MARKERS = (
    "SYNTHETIC^PRIVATE^NAME",
    "SYNTHETIC-PATIENT-ID-4678",
    "19700123",
    "SYN-ACCESS-489",
    "SYNTHETIC FREE TEXT DESCRIPTION",
    "SYNTHETIC PRIVATE TAG CONTENT",
)


def synthetic_dataset(
    modality: str = "CT", *, overrides: dict | None = None, omit: tuple = (),
) -> FileDataset:
    """Create a small valid CT/MR image object containing artificial PHI markers."""
    sop = MRImageStorage if modality == "MR" else CTImageStorage
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = sop
    meta.MediaStorageSOPInstanceUID = SYNTHETIC_INSTANCE_UID
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    dataset = FileDataset(None, {}, file_meta=meta, preamble=b"\0" * 128)
    values = {
        "SOPClassUID": sop,
        "SOPInstanceUID": SYNTHETIC_INSTANCE_UID,
        "StudyInstanceUID": SYNTHETIC_STUDY_UID,
        "SeriesInstanceUID": SYNTHETIC_SERIES_UID,
        "Modality": modality,
        "BodyPartExamined": "KNEE",
        "Laterality": "R",
        "ImageLaterality": "R",
        "Rows": 2,
        "Columns": 3,
        "SamplesPerPixel": 1,
        "PhotometricInterpretation": "MONOCHROME2",
        "BitsAllocated": 16,
        "BitsStored": 12,
        "HighBit": 11,
        "PixelRepresentation": 0,
        "PixelSpacing": [0.5, 0.5],
        "ImageOrientationPatient": [1, 0, 0, 0, 1, 0],
        "SliceThickness": 1.5,
        "PatientName": IDENTIFYING_MARKERS[0],
        "PatientID": IDENTIFYING_MARKERS[1],
        "PatientBirthDate": IDENTIFYING_MARKERS[2],
        "AccessionNumber": IDENTIFYING_MARKERS[3],
        "StudyDescription": IDENTIFYING_MARKERS[4],
        "PixelData": b"\0" * 12,
    }
    values.update(overrides or {})
    for keyword, value in values.items():
        if keyword not in omit:
            setattr(dataset, keyword, value)
    dataset.add_new((0x0011, 0x0010), "LO", "SYNTHETIC_CREATOR")
    dataset.add_new((0x0011, 0x1010), "LO", IDENTIFYING_MARKERS[5])
    return dataset


def write_synthetic_dicom(
    path: str | Path, modality: str = "CT", *, overrides: dict | None = None,
    omit: tuple = (),
) -> FileDataset:
    dataset = synthetic_dataset(modality, overrides=overrides, omit=omit)
    pydicom.dcmwrite(path, dataset, enforce_file_format=True)
    return dataset
