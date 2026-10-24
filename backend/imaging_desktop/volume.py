"""Real single-frame DICOM pixel loader using the existing metadata/series gate.

Different from the synthetic-only reconstructor: no fixture marker, patient-ID
read, caller-invented acquisition manifest, toy labels or 96-voxel restriction.
"""

from dataclasses import dataclass, field
from io import BytesIO
import hashlib
import secrets

import numpy as np
import pydicom

from backend.app.imaging_intelligence.reader import _BoundedFile, _TAGS, _private_parser, _transfer_syntax_preflight
from backend.app.imaging_intelligence.series import (
    SeriesInstance, SeriesMetadataReader, StudySeriesValidator, _GEOMETRY_TAGS,
)
from .sources import ImportFailure, SourceFiles, MAX_FILE_BYTES, MAX_FILES, check_cancel


MAX_VOXELS = 64*1024*1024
ALLOWED_TRANSFERS = {"1.2.840.10008.1.2", "1.2.840.10008.1.2.1", "1.2.840.10008.1.2.2"}


@dataclass(frozen=True)
class CatalogSeries:
    reference: str
    modality: str
    count: int
    shape_yx: tuple[int, int]
    issues: tuple[str, ...]
    assessment: object = field(repr=False)
    items: tuple = field(repr=False)
    snapshots: tuple[bytes, ...] = field(repr=False)


@dataclass(frozen=True)
class Catalog:
    series: tuple[CatalogSeries, ...]
    ignored_files: int
    key: bytes = field(repr=False)


@dataclass(frozen=True)
class DisplayVolume:
    voxels: np.ndarray = field(repr=False)  # z, y, x; rescaled DICOM values
    affine_lps: np.ndarray = field(repr=False)
    modality: str
    monochrome1: bool
    source_sha256: str
    series_reference: str
    completeness: str = "not_established"

    def __post_init__(self):
        data = np.array(self.voxels, dtype="<f4", copy=True)
        affine = np.array(self.affine_lps, dtype=float, copy=True)
        if (data.ndim != 3 or any(n < 2 or n > 512 for n in data.shape) or data.size > MAX_VOXELS
                or not np.isfinite(data).all() or affine.shape != (4, 4) or not np.isfinite(affine).all()
                or not np.allclose(affine[3], [0, 0, 0, 1]) or np.linalg.det(affine[:3, :3]) <= 0):
            raise ImportFailure("invalid_volume")
        data.setflags(write=False)
        affine.setflags(write=False)
        object.__setattr__(self, "voxels", data)
        object.__setattr__(self, "affine_lps", affine)

    def report(self):
        return {"profile": "desktop-classic-dicom-volume-v1", "modality": self.modality,
                "shape_zyx": list(self.voxels.shape), "affine_lps": self.affine_lps.tolist(),
                "source_sha256": self.source_sha256, "series_reference": self.series_reference,
                "completeness": self.completeness, "patient_identity_verified": False,
                "segmentation_performed": False, "is_clinically_validated": False}


def _metadata(raw, reader):
    try:
        stream = _BoundedFile(BytesIO(raw), len(raw))
        with _private_parser() as warnings:
            if _transfer_syntax_preflight(stream) not in ALLOWED_TRANSFERS:
                raise ImportFailure("compressed_dicom_not_supported")
            stream.seek(0)
            ds = pydicom.dcmread(stream, force=False, stop_before_pixels=True, specific_tags=list(_TAGS+_GEOMETRY_TAGS))
            if str(getattr(ds, "SOPClassUID", "")) == "1.2.840.10008.1.3.10":
                return None  # DICOMDIR is an index, not an image slice.
            metadata = reader._base._extract(ds)
            geometry, issues = reader._geometry(ds)
            if warnings or metadata.status != "valid" or issues:
                raise ImportFailure("invalid_dicom_metadata")
            t = metadata.technical
            if (metadata.modality not in {"MR", "CT"} or t.number_of_frames not in (None, 1)
                    or t.samples_per_pixel != 1 or t.photometric_interpretation not in {"MONOCHROME1", "MONOCHROME2"}
                    or t.bits_allocated not in (8, 16) or not 2 <= t.rows <= 512 or not 2 <= t.columns <= 512):
                raise ImportFailure("classic_monochrome_mr_ct_required")
            return SeriesInstance(metadata, geometry, tuple(issues))
    except ImportFailure:
        raise
    except Exception:
        raise ImportFailure("invalid_dicom_metadata") from None


def scan(source: SourceFiles, *, cancel=None):
    if type(source) is not SourceFiles or not 1 <= len(source.files) <= MAX_FILES:
        raise ImportFailure("file_count_limit")
    key = secrets.token_bytes(32)
    reader = SeriesMetadataReader(reference_key=key, max_file_bytes=MAX_FILE_BYTES)
    groups, seen, ignored = {}, set(), source.ignored_files
    for raw in source.files:
        check_cancel(cancel)
        if not isinstance(raw, bytes) or len(raw) > MAX_FILE_BYTES:
            raise ImportFailure("input_size_limit")
        item = _metadata(raw, reader)
        if item is None:
            ignored += 1
            continue
        ref = item.metadata.instance_reference
        if ref in seen:
            raise ImportFailure("duplicate_dicom_instance")
        seen.add(ref)
        groups.setdefault((item.metadata.study_reference, item.metadata.series_reference), []).append((item, raw))
    result = []
    for group in groups.values():
        items, snapshots = tuple(zip(*group))
        study = StudySeriesValidator(reader).validate(items)
        assessment = study.series[0]
        first = items[0].metadata
        issues = tuple(sorted(set(study.issues) | set(assessment.issues)))
        if len(items) < 2:
            issues += ("two_or_more_slices_required",)
        result.append(CatalogSeries(first.series_reference, first.modality, len(items),
                                    (first.technical.rows, first.technical.columns), issues,
                                    assessment, items, snapshots))
    if not result:
        raise ImportFailure("no_dicom_instances")
    return Catalog(tuple(result), ignored, key)


def load_series(series: CatalogSeries, *, cancel=None):
    if series.issues or series.assessment.status != "valid":
        raise ImportFailure("inconsistent_or_nonrectilinear_series")
    ny, nx = series.shape_yx
    if series.count*ny*nx > MAX_VOXELS:
        raise ImportFailure("voxel_limit")
    lookup, hashes = {}, []
    for item, raw in zip(series.items, series.snapshots):
        check_cancel(cancel)
        try:
            stream = _BoundedFile(BytesIO(raw), len(raw))
            with _private_parser() as warnings:
                ds = pydicom.dcmread(stream, force=False, specific_tags=list(_TAGS+_GEOMETRY_TAGS+(
                    "PixelData", "RescaleSlope", "RescaleIntercept")))
                t = item.metadata.technical
                expected = nx*ny*(t.bits_allocated//8)
                pixels = ds.PixelData
                if len(pixels) != expected+(expected % 2):
                    raise ImportFailure("invalid_pixel_length")
                slope, intercept = float(getattr(ds, "RescaleSlope", 1)), float(getattr(ds, "RescaleIntercept", 0))
                if not np.isfinite([slope, intercept]).all() or slope == 0:
                    raise ImportFailure("invalid_rescale")
                data = ds.pixel_array.astype(np.float32)*slope + intercept
                if warnings or data.shape != (ny, nx) or not np.isfinite(data).all():
                    raise ImportFailure("invalid_pixels")
                lookup[item.metadata.instance_reference] = data
                hashes.append(hashlib.sha256(raw).digest())
        except ImportFailure:
            raise
        except Exception:
            raise ImportFailure("pixel_decode_failed") from None
    refs = series.assessment.ordered_instance_references
    first = next(item for item in series.items if item.metadata.instance_reference == refs[0])
    iop = np.asarray(first.metadata.technical.image_orientation_patient)
    row, col = first.metadata.technical.pixel_spacing
    affine = np.eye(4)
    affine[:3, :3] = np.column_stack((iop[:3]*col, iop[3:]*row, np.cross(iop[:3], iop[3:])*series.assessment.slice_step_mm))
    affine[:3, 3] = first.geometry.image_position_patient
    return DisplayVolume(np.stack([lookup[ref] for ref in refs]), affine, series.modality,
                         first.metadata.technical.photometric_interpretation == "MONOCHROME1",
                         hashlib.sha256(b"".join(sorted(hashes))).hexdigest(), series.reference)


def demonstration(*, cancel=None):
    from tempfile import TemporaryDirectory
    from pathlib import Path
    from backend.tools.synthetic_knee_fixture import generate_knee_dicom
    with TemporaryDirectory(prefix="4b-synthetic-desktop-") as folder:
        fixture = generate_knee_dicom(Path(folder), size=64, anatomical=True)
        check_cancel(cancel)
        return scan(SourceFiles(tuple(item.path.read_bytes() for item in fixture.source.instances)), cancel=cancel)
