"""Generate synthetic MR slices and run the offline series validation pipeline."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pydicom

from backend.app.imaging_intelligence.reader import _reference
from backend.app.imaging_intelligence.series import (
    ExpectedSeries, SeriesMetadataReader, StudySeriesValidator,
)
from backend.tools.imaging_metadata_demo import SYNTHETIC_REFERENCE_KEY, write_synthetic_dicom


SYNTHETIC_STUDY_UID = "1.2.826.0.1.3680043.10.543.2001"
SYNTHETIC_SERIES_UID = "1.2.826.0.1.3680043.10.543.2002"
SYNTHETIC_FRAME_UID = "1.2.826.0.1.3680043.10.543.2003"


@dataclass(frozen=True)
class SyntheticSeries:
    files: tuple[Path, ...]
    expected: ExpectedSeries


def generate_synthetic_series(directory: Path, *, count: int = 3) -> SyntheticSeries:
    if type(count) is not int or not 1 <= count <= 16:
        raise ValueError("Synthetic slice count must be between 1 and 16.")
    directory.mkdir(parents=True, exist_ok=True)
    files, references = [], []
    for index in range(count):
        path = directory / f"synthetic-{index + 1:03}.dcm"
        write_synthetic_dicom(path)
        dataset = pydicom.dcmread(path)
        uid = f"1.2.826.0.1.3680043.10.543.210{index}"
        dataset.StudyInstanceUID, dataset.SeriesInstanceUID = SYNTHETIC_STUDY_UID, SYNTHETIC_SERIES_UID
        dataset.SOPInstanceUID = dataset.file_meta.MediaStorageSOPInstanceUID = uid
        dataset.FrameOfReferenceUID = SYNTHETIC_FRAME_UID
        dataset.ImagePositionPatient = [0, 0, index * 3]
        dataset.InstanceNumber = index + 1
        dataset.SpacingBetweenSlices = 3
        dataset.StudyID = "SYNTHETIC"
        dataset.SeriesNumber = 1
        dataset.StudyDate, dataset.StudyTime = "20000101", "000000"
        dataset.PatientSex = "O"
        dataset.ImageType = ["ORIGINAL", "PRIMARY", "OTHER"]
        dataset.ScanningSequence, dataset.SequenceVariant = "SE", "NONE"
        dataset.MRAcquisitionType = "2D"
        dataset.RepetitionTime, dataset.EchoTime = 1000, 10
        dataset.PixelData = b"".join((index * 100 + i * 16).to_bytes(2, "little") for i in range(16))
        dataset.save_as(path, enforce_file_format=True)
        files.append(path)
        references.append(_reference(SYNTHETIC_REFERENCE_KEY, "instance", uid))
    return SyntheticSeries(tuple(files), ExpectedSeries(
        _reference(SYNTHETIC_REFERENCE_KEY, "series", SYNTHETIC_SERIES_UID), tuple(references),
    ))


def run_series_demo():
    validator = StudySeriesValidator(SeriesMetadataReader(reference_key=SYNTHETIC_REFERENCE_KEY))
    with TemporaryDirectory(prefix="4b-synthetic-series-") as folder:
        fixture = generate_synthetic_series(Path(folder))
        complete = validator.read(reversed(fixture.files), expected=(fixture.expected,))
        missing = validator.read(fixture.files[:-1], expected=(fixture.expected,))
        unknown = validator.read(fixture.files)
        duplicate = validator.read(fixture.files + fixture.files[:1], expected=(fixture.expected,))
    return {"synthetic_only": True, "is_diagnosis": False,
            "complete": complete.to_dict(), "missing_slice": missing.to_dict(),
            "inventory_unknown": unknown.to_dict(), "duplicate_instance": duplicate.to_dict()}


if __name__ == "__main__":
    print(json.dumps(run_series_demo(), sort_keys=True, indent=2, allow_nan=False))
