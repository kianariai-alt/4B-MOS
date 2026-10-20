"""Privacy-minimized metadata contracts, independent of persistence and transport."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Literal


METADATA_SCHEMA_VERSION = "imaging-metadata-v1"
READER_VERSION = "1.0.0"


def canonical_digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class MetadataIssue:
    code: str
    field: str
    severity: Literal["missing", "error"]


@dataclass(frozen=True, slots=True)
class TechnicalMetadata:
    sop_class_uid: str | None = None
    transfer_syntax_uid: str | None = None
    rows: int | None = None
    columns: int | None = None
    samples_per_pixel: int | None = None
    photometric_interpretation: str | None = None
    bits_allocated: int | None = None
    bits_stored: int | None = None
    high_bit: int | None = None
    pixel_representation: int | None = None
    number_of_frames: int | None = None
    pixel_spacing: tuple[float, float] | None = None
    slice_thickness: float | None = None
    image_orientation_patient: tuple[float, ...] | None = None

    def present_fields(self) -> tuple[str, ...]:
        return tuple(k for k, v in asdict(self).items() if v is not None)


@dataclass(frozen=True, slots=True)
class DicomMetadataReport:
    status: Literal["valid", "incomplete", "invalid"]
    modality: str | None = None
    study_reference: str | None = None
    series_reference: str | None = None
    instance_reference: str | None = None
    body_region: str | None = None
    laterality: str | None = None
    technical: TechnicalMetadata = TechnicalMetadata()
    issues: tuple[MetadataIssue, ...] = ()
    schema_version: str = METADATA_SCHEMA_VERSION
    reader_version: str = READER_VERSION
    pixel_data_validated: bool = False
    dicom_identity_verified: bool = False

    def _payload(self) -> dict:
        # JSON round-trip normalizes tuples to arrays, without allowing NaN.
        return json.loads(json.dumps(asdict(self), allow_nan=False))

    @property
    def metadata_sha256(self) -> str:
        return canonical_digest(self._payload())

    def to_dict(self) -> dict:
        return {**self._payload(), "metadata_sha256": self.metadata_sha256}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, allow_nan=False)
