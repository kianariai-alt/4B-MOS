"""Analytic toy anatomy and generated MR/CT DICOM, never a patient segmentation."""

from dataclasses import dataclass
import hashlib
from pathlib import Path

import numpy as np
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, MRImageStorage

from backend.app.imaging_intelligence.reader import _reference
from backend.app.imaging_intelligence.reconstruction import (
    SYNTHETIC_PATIENT_MARKER, SyntheticInstance, SyntheticVolumeInput,
)
from backend.app.imaging_intelligence.series import ExpectedSeries
from backend.tools.imaging_metadata_demo import SYNTHETIC_REFERENCE_KEY


STRUCTURES = (
    (1, "femur", "استخوان ران", "#eee7d5"),
    (2, "tibia", "استخوان درشت‌نی", "#cdd9e5"),
    (3, "patella", "کشکک", "#f7d8bc"),
    (4, "cartilage", "غضروف", "#49d8cb"),
    (5, "medial_meniscus", "منیسک داخلی", "#f3bd53"),
    (6, "lateral_meniscus", "منیسک خارجی", "#f18b49"),
    (7, "acl", "رباط صلیبی قدامی", "#ee7183"),
    (8, "pcl", "رباط صلیبی خلفی", "#a293fa"),
)


@dataclass(frozen=True)
class SyntheticKneeFixture:
    source: SyntheticVolumeInput
    labels: np.ndarray
    expected_values: np.ndarray


def analytic_knee(size=64, modality="MR"):
    if type(size) is not int or size not in {32, 48, 64, 96} or modality not in {"MR", "CT"}:
        raise ValueError("Unsupported synthetic knee configuration.")
    z, y, x = np.meshgrid(*(np.linspace(-1, 1, size) for _ in range(3)), indexing="ij")
    labels = np.zeros((size, size, size), dtype=np.uint8)

    def ellipsoid(cx, cy, cz, rx, ry, rz):
        return ((x-cx)/rx)**2 + ((y-cy)/ry)**2 + ((z-cz)/rz)**2 < 1

    femur = ((x/.27)**2 + (y/.23)**2 < 1) & (z > .30) & (z < .94)
    condyles = np.zeros_like(femur)
    outer = np.zeros_like(femur)
    for cx in (-.28, .28):
        condyles |= ellipsoid(cx, 0, .25, .25, .35, .28)
        outer |= ellipsoid(cx, 0, .25, .29, .39, .32)
    femur |= condyles
    tibia = (((x/.34)**2 + (y/.27)**2 < 1) & (z < -.40) & (z > -.94))
    plateau = ellipsoid(0, 0, -.43, .57, .42, .17)
    tibia |= plateau
    labels[femur] = 1
    labels[tibia] = 2
    labels[ellipsoid(0, -.58, .16, .27, .15, .29)] = 3
    cartilage = ((outer & ~femur & (z < .30)) |
                 (ellipsoid(0, 0, -.43, .60, .45, .21) & ~tibia & (z > -.40)))
    labels[cartilage & (labels == 0)] = 4
    for label, cx in ((5, -.29), (6, .29)):
        radius = np.sqrt(((x-cx)/.23)**2 + (y/.29)**2)
        ring = ((radius-1)/.26)**2 + ((z+.13)/.06)**2 < 1
        crescent = ring & ((x-cx) * np.sign(cx) > -.15)
        labels[crescent & (labels == 0)] = label

    def ligament(start, end, radius):
        a, b = np.asarray(start), np.asarray(end)
        d = b-a
        t = ((x-a[0])*d[0] + (y-a[1])*d[1] + (z-a[2])*d[2]) / (d @ d)
        distance = (x-a[0]-t*d[0])**2 + (y-a[1]-t*d[1])**2 + (z-a[2]-t*d[2])**2
        return (distance < radius**2) & (t >= 0) & (t <= 1)

    labels[ligament((-.12, .13, -.31), (.12, -.12, .31), .065) & (labels == 0)] = 7
    labels[ligament((.12, .18, -.31), (-.12, .23, .31), .07) & (labels == 0)] = 8
    body = (x/.90)**2 + (y/.85)**2 + (z/1.05)**2 < 1
    if modality == "MR":
        values = np.where(body, 90, 0).astype(np.int16)
        intensities = (0, 430, 410, 420, 870, 170, 180, 120, 135)
    else:
        values = np.where(body, 45, -1000).astype(np.int16)
        intensities = (0, 950, 900, 930, 65, 55, 58, 60, 62)
    for label in range(1, 9):
        values[labels == label] = intensities[label]
    # An index-dependent gradient makes ordering/orientation errors observable.
    values += (np.arange(size, dtype=np.int16)[:, None, None] % 7)
    labels.setflags(write=False)
    values.setflags(write=False)
    return labels, values


def generate_knee_dicom(directory: Path, *, modality="MR", size=64,
                        spacing_xyz=(.8, 1., 1.4), orientation=(1., 0., 0., 0., 1., 0.)):
    labels, values = analytic_knee(size, modality)
    spacing = np.asarray(spacing_xyz, dtype=float)
    iop = np.asarray(orientation, dtype=float)
    if (spacing.shape != (3,) or not np.isfinite(spacing).all() or np.any(spacing <= 0)
            or iop.shape != (6,) or not np.isfinite(iop).all()
            or not np.isclose(np.linalg.norm(iop[:3]), 1) or not np.isclose(np.linalg.norm(iop[3:]), 1)
            or not np.isclose(iop[:3] @ iop[3:], 0)):
        raise ValueError("Invalid synthetic geometry.")
    affine = np.eye(4)
    affine[:3, :3] = np.column_stack((iop[:3], iop[3:], np.cross(iop[:3], iop[3:]))) * spacing
    affine[:3, 3] = -affine[:3, :3] @ np.full(3, (size-1)/2)
    directory.mkdir(parents=True, exist_ok=True)
    branch = 31 if modality == "MR" else 32
    root = f"1.2.826.0.1.3680043.10.543.{branch}"
    sop = MRImageStorage if modality == "MR" else CTImageStorage
    instances, references = [], []
    for index in range(size):
        path = directory / f"generated-{index:03}.dcm"
        uid = f"{root}.4.{index+1}"
        meta = FileMetaDataset()
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        meta.MediaStorageSOPClassUID, meta.MediaStorageSOPInstanceUID = sop, uid
        meta.ImplementationClassUID = f"{root}.9"
        ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0"*128)
        ds.SOPClassUID, ds.SOPInstanceUID = sop, uid
        ds.StudyInstanceUID, ds.SeriesInstanceUID, ds.FrameOfReferenceUID = f"{root}.1", f"{root}.2", f"{root}.3"
        ds.PatientName, ds.PatientID = "SYNTHETIC^KNEE_ONLY", SYNTHETIC_PATIENT_MARKER
        ds.Modality, ds.BodyPartExamined, ds.ImageLaterality = modality, "KNEE", "L"
        ds.Rows = ds.Columns = size
        ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, "MONOCHROME2"
        ds.BitsAllocated = ds.BitsStored = 16
        ds.HighBit, ds.PixelRepresentation = 15, int(modality == "CT")
        ds.PixelSpacing = [float(spacing[1]), float(spacing[0])]
        ds.SliceThickness = ds.SpacingBetweenSlices = float(spacing[2])
        ds.ImageOrientationPatient = list(map(float, iop))
        ds.ImagePositionPatient = list(map(float, (affine @ [0, 0, index, 1])[:3]))
        ds.InstanceNumber = index+1
        ds.RescaleSlope, ds.RescaleIntercept = 1, 0
        ds.PixelData = values[index].astype("<i2" if modality == "CT" else "<u2").tobytes()
        ds.save_as(path, enforce_file_format=True)
        instances.append(SyntheticInstance(path, hashlib.sha256(path.read_bytes()).hexdigest()))
        references.append(_reference(SYNTHETIC_REFERENCE_KEY, "instance", uid))
    source = SyntheticVolumeInput(tuple(instances), ExpectedSeries(
        _reference(SYNTHETIC_REFERENCE_KEY, "series", f"{root}.2"), tuple(references)),
        values.shape, tuple(map(tuple, affine.tolist())), modality)
    return SyntheticKneeFixture(source, labels, values)
