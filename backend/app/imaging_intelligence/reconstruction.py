"""Bounded voxel reconstruction of generated knee fixtures, without patient input.

This first pixel-processing profile accepts only an explicit, trusted inventory
of synthetic Part 10 files. A marker/hash is not proof of patient identity or
anonymization. No endpoint, generic DICOM loader, network or database is exposed.
"""

from dataclasses import dataclass
from io import BytesIO
import hashlib
import os
from pathlib import Path
import re
import stat

import numpy as np
import pydicom

from .models import canonical_digest
from .reader import _BoundedFile, _TAGS, _private_parser, _transfer_syntax_preflight
from .series import ExpectedSeries, SeriesInstance, SeriesMetadataReader, StudySeriesValidator, _GEOMETRY_TAGS


PROFILE = "synthetic-knee-volume-v1"
SYNTHETIC_PATIENT_MARKER = "4B-SYNTHETIC-KNEE-V1"
MAX_SIDE = 96
MAX_INSTANCE_BYTES = 128 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_REFERENCE = re.compile(r"hmac-sha256:[0-9a-f]{64}\Z")
_PIXEL_TAGS = ("PixelData", "RescaleSlope", "RescaleIntercept", "PatientID")


class VolumeReconstructionError(ValueError):
    """Static, privacy-minimized failure; never carries a path or DICOM value."""


@dataclass(frozen=True)
class SyntheticInstance:
    path: Path
    file_sha256: str


@dataclass(frozen=True)
class SyntheticVolumeInput:
    instances: tuple[SyntheticInstance, ...]
    expected: ExpectedSeries
    shape_zyx: tuple[int, int, int]
    affine_lps: tuple[tuple[float, ...], ...]
    modality: str
    profile: str = PROFILE


@dataclass(frozen=True)
class ReconstructedVolume:
    voxels: np.ndarray  # z, row (j), column (i); values after DICOM rescaling
    affine_lps: np.ndarray  # maps [i,j,k,1] voxel centers to LPS millimetres
    modality: str
    series_sha256: str
    ordered_instance_references: tuple[str, ...]
    source_inventory_sha256: str | None = None

    def __post_init__(self):
        data = np.array(self.voxels, dtype="<f4", copy=True)
        affine = np.array(self.affine_lps, dtype="<f8", copy=True)
        if (data.ndim != 3 or any(not 2 <= x <= MAX_SIDE for x in data.shape)
                or affine.shape != (4, 4) or not np.isfinite(data).all()
                or not np.isfinite(affine).all() or not np.allclose(affine[3], [0, 0, 0, 1])
                or np.linalg.det(affine[:3, :3]) <= 0 or self.modality not in {"MR", "CT"}
                or type(self.series_sha256) is not str or not _SHA.fullmatch(self.series_sha256)
                or type(self.ordered_instance_references) is not tuple
                or len(self.ordered_instance_references) != data.shape[0]
                or any(type(x) is not str or not _REFERENCE.fullmatch(x) for x in self.ordered_instance_references)
                or len(set(self.ordered_instance_references)) != data.shape[0]):
            raise VolumeReconstructionError("invalid_reconstructed_volume")
        if self.source_inventory_sha256 is not None and (
                type(self.source_inventory_sha256) is not str or not _SHA.fullmatch(self.source_inventory_sha256)):
            raise VolumeReconstructionError("invalid_source_inventory_digest")
        data.setflags(write=False)
        affine.setflags(write=False)
        object.__setattr__(self, "voxels", data)
        object.__setattr__(self, "affine_lps", affine)

    def to_manifest(self):
        data = {
            "schema_version": PROFILE, "synthetic_only": True,
            "modality": self.modality, "shape_zyx": list(self.voxels.shape),
            "spacing_xyz_mm": np.linalg.norm(self.affine_lps[:3, :3], axis=0).tolist(),
            "affine_lps": self.affine_lps.tolist(), "coordinate_system": "LPS_mm",
            "voxel_convention": "centers_ijk_to_lps", "array_order": "zyx",
            "value_unit": "synthetic_HU" if self.modality == "CT" else "synthetic_MR_arbitrary",
            "voxel_sha256": hashlib.sha256(self.voxels.tobytes(order="C")).hexdigest(),
            "series_sha256": self.series_sha256,
            "input_file_inventory_sha256": self.source_inventory_sha256,
            "source_instance_references": list(self.ordered_instance_references),
            "pixel_profile": "single_frame_uncompressed_16bit_rescaled",
            "resampling_applied": False, "dicom_identity_verified": False,
            "is_clinically_validated": False, "is_diagnosis": False,
        }
        return {**data, "volume_sha256": canonical_digest(data)}


class SyntheticVolumeReconstructor:
    """Reuses the existing metadata/geometry gate and parses each byte snapshot once."""

    def __init__(self, *, reference_key: bytes):
        self.reader = SeriesMetadataReader(reference_key=reference_key, max_file_bytes=MAX_INSTANCE_BYTES)

    def reconstruct(self, source: SyntheticVolumeInput) -> ReconstructedVolume:
        if (type(source) is not SyntheticVolumeInput or source.profile != PROFILE
                or source.modality not in {"MR", "CT"}
                or type(source.instances) is not tuple or not 2 <= len(source.instances) <= MAX_SIDE
                or type(source.shape_zyx) is not tuple or len(source.shape_zyx) != 3
                or any(type(x) is not int or not 2 <= x <= MAX_SIDE for x in source.shape_zyx)
                or len(source.instances) != source.shape_zyx[0]
                or type(source.expected) is not ExpectedSeries
                or len(source.expected.instance_references) != len(source.instances)
                or any(type(x) is not SyntheticInstance or type(x.file_sha256) is not str
                       or not _SHA.fullmatch(x.file_sha256) for x in source.instances)):
            raise VolumeReconstructionError("invalid_synthetic_inventory")
        items, pixels, positions = [], {}, {}
        for instance in source.instances:
            item, data = self._read_snapshot(instance, source.modality)
            ref = item.metadata.instance_reference
            if ref in pixels:
                raise VolumeReconstructionError("duplicate_synthetic_instance")
            if data.shape != source.shape_zyx[1:]:
                raise VolumeReconstructionError("pixel_shape_mismatch")
            items.append(item)
            pixels[ref] = data
            positions[ref] = item.geometry.image_position_patient
        study = StudySeriesValidator(self.reader).validate(tuple(items), expected=(source.expected,))
        if (study.status != "valid" or len(study.series) != 1
                or study.series[0].completeness != "expected_manifest_matched"):
            raise VolumeReconstructionError("series_geometry_not_ready")
        series = study.series[0]
        first_ref = series.ordered_instance_references[0]
        first = next(x.metadata for x in items if x.metadata.instance_reference == first_ref)
        iop = np.asarray(first.technical.image_orientation_patient, dtype=float)
        row_spacing, column_spacing = first.technical.pixel_spacing
        affine = np.eye(4)
        # DICOM's first IOP vector follows column-index movement (i).
        affine[:3, 0] = iop[:3] * column_spacing
        affine[:3, 1] = iop[3:] * row_spacing
        affine[:3, 2] = np.cross(iop[:3], iop[3:]) * series.slice_step_mm
        affine[:3, 3] = positions[first_ref]
        try:
            expected_affine = np.asarray(source.affine_lps, dtype=float)
            aligned = expected_affine.shape == (4, 4) and np.allclose(affine, expected_affine, atol=1e-6, rtol=0)
        except (TypeError, ValueError):
            aligned = False
        if not aligned:
            raise VolumeReconstructionError("synthetic_label_grid_mismatch")
        volume = np.stack([pixels[ref] for ref in series.ordered_instance_references])
        return ReconstructedVolume(volume, affine, source.modality, series.sha256,
                                   series.ordered_instance_references,
                                   canonical_digest({"file_sha256s": sorted(x.file_sha256 for x in source.instances)}))

    def _read_snapshot(self, instance, modality):
        try:
            fd = os.open(instance.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as raw:
                info = os.fstat(raw.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_INSTANCE_BYTES:
                    raise VolumeReconstructionError("synthetic_file_limit_or_type")
                content = raw.read(MAX_INSTANCE_BYTES + 1)
            if hashlib.sha256(content).hexdigest() != instance.file_sha256:
                raise VolumeReconstructionError("synthetic_file_hash_mismatch")
            stream = _BoundedFile(BytesIO(content), len(content))
            with _private_parser() as warnings:
                if _transfer_syntax_preflight(stream) != "1.2.840.10008.1.2.1":
                    raise VolumeReconstructionError("unsupported_synthetic_pixel_encoding")
                stream.seek(0)
                ds = pydicom.dcmread(stream, force=False,
                    specific_tags=list(_TAGS + _GEOMETRY_TAGS + _PIXEL_TAGS))
                if ds.PatientID != SYNTHETIC_PATIENT_MARKER or ds.Modality != modality:
                    raise VolumeReconstructionError("synthetic_fixture_marker_required")
                metadata = self.reader._base._extract(ds)
                geometry, issues = self.reader._geometry(ds)
                if (metadata.status != "valid" or issues or ds.BitsAllocated != 16
                        or ds.BitsStored != 16 or ds.HighBit != 15
                        or ds.SamplesPerPixel != 1 or ds.PhotometricInterpretation != "MONOCHROME2"
                        or getattr(ds, "NumberOfFrames", 1) != 1
                        or ds.PixelRepresentation != (1 if modality == "CT" else 0)
                        or not 2 <= ds.Rows <= MAX_SIDE or not 2 <= ds.Columns <= MAX_SIDE
                        or len(ds.PixelData) != ds.Rows * ds.Columns * 2):
                    raise VolumeReconstructionError("unsupported_synthetic_pixel_profile")
                slope = float(getattr(ds, "RescaleSlope", 1))
                intercept = float(getattr(ds, "RescaleIntercept", 0))
                if not np.isfinite([slope, intercept]).all() or slope <= 0:
                    raise VolumeReconstructionError("invalid_pixel_rescaling")
                data = ds.pixel_array.astype(np.float32) * slope + intercept
                if not np.isfinite(data).all() or warnings:
                    raise VolumeReconstructionError("invalid_synthetic_pixel_data")
            return SeriesInstance(metadata, geometry), data
        except VolumeReconstructionError:
            raise
        except Exception:
            raise VolumeReconstructionError("synthetic_dicom_unavailable_or_invalid") from None
