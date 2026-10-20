"""Classic single-frame CT/MR series checks; no pixel interpretation or identity proof."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import os
from pathlib import Path
import re
import stat
from statistics import median
from typing import Iterable

import pydicom
from pydicom.uid import UID

from .models import DicomMetadataReport, MetadataIssue, canonical_digest
from .reader import (
    DEFAULT_MAX_FILE_BYTES, DicomMetadataReader, _BoundedFile, _private_parser,
    _reference, _TAGS, _transfer_syntax_preflight, _valid_uid,
)


SERIES_SCHEMA_VERSION = "series-validation-v1"
_REF = re.compile(r"hmac-sha256:[0-9a-f]{64}\Z")
_GEOMETRY_TAGS = ("ImagePositionPatient", "InstanceNumber", "FrameOfReferenceUID", "SpacingBetweenSlices")


@dataclass(frozen=True, slots=True)
class InstanceGeometry:
    image_position_patient: tuple[float, float, float] | None = None
    frame_reference: str | None = None
    instance_number: int | None = None
    spacing_between_slices: float | None = None


@dataclass(frozen=True, slots=True)
class SeriesInstance:
    metadata: DicomMetadataReport
    geometry: InstanceGeometry = InstanceGeometry()
    issues: tuple[MetadataIssue, ...] = ()

    @property
    def status(self) -> str:
        if self.metadata.status == "invalid" or any(i.severity == "error" for i in self.issues):
            return "invalid"
        return "incomplete" if self.metadata.status != "valid" or self.issues else "valid"

    @property
    def sha256(self) -> str:
        return canonical_digest(self.to_dict())

    def to_dict(self) -> dict:
        return {"metadata": self.metadata.to_dict(), "geometry": asdict(self.geometry),
                "issues": [asdict(i) for i in self.issues], "status": self.status}


class SeriesMetadataReader:
    """Read metadata and geometry from one bounded file descriptor, without rereading a path."""

    def __init__(self, *, reference_key: bytes, max_file_bytes: int = DEFAULT_MAX_FILE_BYTES):
        self._base = DicomMetadataReader(reference_key=reference_key, max_file_bytes=max_file_bytes)
        self._key = reference_key
        self.max_file_bytes = max_file_bytes

    def read(self, path: str | Path) -> SeriesInstance:
        def fail(code):
            return SeriesInstance(self._base._failure(code))
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as raw:
                info = os.fstat(raw.fileno())
                if not stat.S_ISREG(info.st_mode):
                    return fail("local_regular_file_required")
                if info.st_size > self.max_file_bytes:
                    return fail("file_size_limit_exceeded")
                stream = _BoundedFile(raw, info.st_size)
                with _private_parser() as captured:
                    transfer = _transfer_syntax_preflight(stream)
                    if (not _valid_uid(transfer) or not UID(transfer).is_transfer_syntax
                            or transfer == "1.2.840.10008.1.2.1.99"):
                        return fail("unsupported_transfer_syntax")
                    stream.seek(0)
                    dataset = pydicom.dcmread(stream, force=False, stop_before_pixels=True,
                                              specific_tags=list(_TAGS + _GEOMETRY_TAGS))
                    metadata = self._base._extract(dataset)
                    geometry, issues = self._geometry(dataset)
                    if metadata.technical.number_of_frames not in (None, 1):
                        issues.append(MetadataIssue("multiframe_geometry_not_supported", "NumberOfFrames", "missing"))
                    if captured:
                        return fail("dicom_parser_warning")
                    return SeriesInstance(metadata, geometry, tuple(issues))
        except OSError:
            return fail("local_file_unavailable")
        except Exception:
            return fail("invalid_dicom_file")

    def _geometry(self, dataset):
        issues = []
        position = getattr(dataset, "ImagePositionPatient", None)
        if position is not None:
            try:
                position = tuple(float(x) for x in position)
                if len(position) != 3 or not all(math.isfinite(x) for x in position):
                    raise ValueError()
            except (ValueError, TypeError, OverflowError):
                issues.append(MetadataIssue("invalid_image_position", "ImagePositionPatient", "error"))
                position = None
        frame = getattr(dataset, "FrameOfReferenceUID", None)
        if frame is not None and not _valid_uid(frame):
            issues.append(MetadataIssue("invalid_frame_reference", "FrameOfReferenceUID", "error"))
            frame = None
        number = getattr(dataset, "InstanceNumber", None)
        if number is not None:
            if isinstance(number, bool) or not isinstance(number, int) or number < 1:
                issues.append(MetadataIssue("invalid_instance_number", "InstanceNumber", "error"))
                number = None
            else:
                number = int(number)
        step = getattr(dataset, "SpacingBetweenSlices", None)
        if step is not None:
            try:
                step = float(step)
                if not math.isfinite(step) or step <= 0:
                    raise ValueError()
            except (ValueError, TypeError, OverflowError):
                issues.append(MetadataIssue("invalid_slice_spacing", "SpacingBetweenSlices", "error"))
                step = None
        return InstanceGeometry(position, _reference(self._key, "frame", frame) if frame else None,
                                number, step), issues


@dataclass(frozen=True, slots=True)
class ExpectedSeries:
    """Externally supplied inventory; count alone cannot establish completeness."""

    series_reference: str
    instance_references: tuple[str, ...]

    def __post_init__(self):
        if (not isinstance(self.series_reference, str) or not _REF.fullmatch(self.series_reference)
                or type(self.instance_references) is not tuple or not 1 <= len(self.instance_references) <= 512
                or any(type(x) is not str or not _REF.fullmatch(x) for x in self.instance_references)
                or len(set(self.instance_references)) != len(self.instance_references)):
            raise ValueError("Invalid expected series inventory.")


@dataclass(frozen=True, slots=True)
class SeriesAssessment:
    study_reference: str
    series_reference: str
    status: str
    modality: str | None
    body_region: str | None
    laterality: str | None
    instance_count: int
    instance_sha256s: tuple[str, ...]
    ordered_instance_references: tuple[str, ...]
    common_technical_fields: tuple[str, ...]
    slice_step_mm: float | None
    completeness: str
    issues: tuple[str, ...]
    expected_inventory_sha256: str | None
    schema_version: str = SERIES_SCHEMA_VERSION
    pixel_data_validated: bool = False
    dicom_identity_verified: bool = False

    @property
    def sha256(self):
        return canonical_digest(asdict(self))

    def to_dict(self):
        return {**asdict(self), "series_sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class StudyAssessment:
    status: str
    input_count: int
    rejected_input_count: int
    series: tuple[SeriesAssessment, ...]
    issues: tuple[str, ...]
    schema_version: str = SERIES_SCHEMA_VERSION
    is_diagnosis: bool = False

    def to_dict(self):
        payload = {**asdict(self), "series": [s.to_dict() for s in self.series]}
        return {**payload, "study_sha256": canonical_digest(payload)}


def _close(a: tuple, b: tuple, tolerance=1e-4):
    return len(a) == len(b) and all(abs(x-y) <= tolerance for x, y in zip(a, b))


class StudySeriesValidator:
    """Rectilinear, single-frame CT/MR volume profile. No inferred acquisition inventory."""

    def __init__(self, reader: SeriesMetadataReader, *, max_instances: int = 512):
        if type(max_instances) is not int or not 1 <= max_instances <= 512:
            raise ValueError("Instance limit must be between 1 and 512.")
        self.reader, self.max_instances = reader, max_instances

    def read(self, paths: Iterable[str | Path], *, expected: tuple[ExpectedSeries, ...] = ()) -> StudyAssessment:
        items = []
        for index, path in enumerate(paths):
            if index >= self.max_instances:
                return StudyAssessment("invalid", index + 1, 0, (), ("instance_limit_exceeded",))
            items.append(self.reader.read(path))
        return self.validate(tuple(items), expected=expected)

    def validate(self, items: tuple[SeriesInstance, ...], *, expected: tuple[ExpectedSeries, ...] = ()) -> StudyAssessment:
        if (type(items) is not tuple or any(type(x) is not SeriesInstance for x in items)
                or type(expected) is not tuple or any(type(x) is not ExpectedSeries for x in expected)
                or len(expected) > self.max_instances
                or len({x.series_reference for x in expected}) != len(expected)):
            raise ValueError("Invalid study validation inputs.")
        if not items:
            return StudyAssessment("incomplete", 0, 0, (), ("no_instances",))
        if len(items) > self.max_instances:
            return StudyAssessment("invalid", len(items), 0, (), ("instance_limit_exceeded",))
        issues, groups, seen, study_refs, series_studies = set(), {}, {}, set(), {}
        rejected = 0
        for item in items:
            m = item.metadata
            if item.status != "valid":
                issues.add("invalid_or_incomplete_instance")
            if not all((m.study_reference, m.series_reference, m.instance_reference)):
                rejected += 1
                continue
            study_refs.add(m.study_reference)
            if m.instance_reference in seen:
                issues.add("duplicate_instance" if seen[m.instance_reference] == item.sha256 else "conflicting_duplicate_instance")
            seen[m.instance_reference] = item.sha256
            if m.series_reference in series_studies and series_studies[m.series_reference] != m.study_reference:
                issues.add("series_reused_across_studies")
            series_studies[m.series_reference] = m.study_reference
            groups.setdefault((m.study_reference, m.series_reference), []).append(item)
        if len(study_refs) > 1:
            issues.add("mixed_studies")
        expected_map = {x.series_reference: x for x in expected}
        if set(expected_map) - {key[1] for key in groups}:
            issues.add("expected_series_missing")
        if expected and {key[1] for key in groups} - set(expected_map):
            issues.add("unexpected_series")
        series = tuple(self._series(key, value, expected_map.get(key[1])) for key, value in sorted(groups.items()))
        fatal = {"duplicate_instance", "conflicting_duplicate_instance", "mixed_studies", "series_reused_across_studies"}
        status = ("invalid" if issues & fatal or any(x.status == "invalid" for x in series)
                  or any(x.status == "invalid" for x in items) else
                  "incomplete" if issues or rejected or any(x.status != "valid" for x in series) else "valid")
        return StudyAssessment(status, len(items), rejected, series, tuple(sorted(issues)))

    def _series(self, key, items, expected):
        issues, incomplete, invalid = set(), False, False
        items = sorted(items, key=lambda x: (x.metadata.instance_reference, x.sha256))
        first = items[0].metadata
        if any(x.status != "valid" for x in items):
            issues.add("instance_metadata_not_valid")
            incomplete = True
        if first.modality not in {"CT", "MR"}:
            issues.add("geometry_profile_not_supported")
            incomplete = True
        for attr in ("modality", "body_region", "laterality"):
            if len({getattr(x.metadata, attr) for x in items}) > 1:
                issues.add("inconsistent_" + attr)
                invalid = True
        for field in ("sop_class_uid", "rows", "columns", "samples_per_pixel", "photometric_interpretation",
                      "bits_allocated", "bits_stored", "high_bit", "pixel_representation"):
            if len({getattr(x.metadata.technical, field) for x in items}) > 1:
                issues.add("inconsistent_" + field)
                invalid = True
        frames = {x.geometry.frame_reference for x in items}
        if len(frames - {None}) > 1:
            issues.add("inconsistent_frame_reference")
            invalid = True
        if None in frames:
            issues.add("missing_frame_reference")
            incomplete = True
        orientation = first.technical.image_orientation_patient
        spacing = first.technical.pixel_spacing
        for field, base in (("image_orientation_patient", orientation), ("pixel_spacing", spacing)):
            values = [getattr(x.metadata.technical, field) for x in items]
            if any(v is None for v in values):
                issues.add("missing_" + field)
                incomplete = True
            elif base is not None and any(not _close(v, base) for v in values):
                issues.add("inconsistent_" + field)
                invalid = True
        positions = [x.geometry.image_position_patient for x in items]
        ordered, step = (), None
        if any(p is None for p in positions):
            issues.add("missing_image_position")
            incomplete = True
        elif orientation is not None and not invalid:
            a, b = orientation[:3], orientation[3:]
            normal = (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
            dot = lambda p, axis: sum(v*w for v, w in zip(p, axis))
            by_position = sorted(zip((dot(p, normal) for p in positions), items), key=lambda pair: (pair[0], pair[1].metadata.instance_reference))
            ordered = tuple(item.metadata.instance_reference for _, item in by_position)
            if any(abs(dot(p, axis)-dot(positions[0], axis)) > 1e-3 for p in positions for axis in (a, b)):
                issues.add("non_rectilinear_stack")
                incomplete = True
            distances = [right[0]-left[0] for left, right in zip(by_position, by_position[1:])]
            if distances:
                step = median(distances)
                if any(x <= 1e-3 for x in distances):
                    issues.add("repeated_slice_position")
                    incomplete = True
                elif any(not math.isclose(x, step, rel_tol=.01, abs_tol=.001) for x in distances):
                    issues.add("non_uniform_slice_spacing")
                    incomplete = True
                declared = [x.geometry.spacing_between_slices for x in items if x.geometry.spacing_between_slices is not None]
                if any(not math.isclose(x, step, rel_tol=.01, abs_tol=.001) for x in declared):
                    issues.add("declared_slice_spacing_mismatch")
                    incomplete = True
        numbers = [x.geometry.instance_number for x in items]
        if None not in numbers and len(numbers) > 1:
            if len(set(numbers)) != len(numbers):
                issues.add("duplicate_instance_number")
                incomplete = True
            elif max(numbers)-min(numbers)+1 != len(numbers):
                issues.add("instance_number_gap_hint")
                incomplete = True
        observed = {x.metadata.instance_reference for x in items}
        matched = expected is not None and observed == set(expected.instance_references)
        if expected is not None and not matched:
            issues.add("expected_instances_mismatch")
            incomplete = True
        common = set(items[0].metadata.technical.present_fields())
        for item in items[1:]:
            common.intersection_update(item.metadata.technical.present_fields())
        return SeriesAssessment(
            *key, "invalid" if invalid else "incomplete" if incomplete else "valid",
            first.modality, first.body_region, first.laterality, len(items),
            tuple(sorted(x.sha256 for x in items)), ordered, tuple(sorted(common)), step,
            "expected_manifest_matched" if matched else "not_established", tuple(sorted(issues)),
            canonical_digest({"series_reference": expected.series_reference,
                              "instances": sorted(expected.instance_references)}) if expected else None,
        )
