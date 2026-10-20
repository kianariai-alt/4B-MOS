"""Bounded local Part 10 DICOM metadata reader; never decodes or exports pixels.

Only selected coded/numeric metadata leaves this module. Raw files are NOT
de-identified. Caller-supplied HMAC keys must be scoped and managed outside it.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import hmac
import logging
import math
import os
import re
import stat
import struct
import warnings
from pathlib import Path

import pydicom
from pydicom.uid import UID

from .models import DicomMetadataReport, MetadataIssue, TechnicalMetadata


DEFAULT_MAX_FILE_BYTES = 64 * 1024 * 1024
_READING = ContextVar("4b_imaging_reader_active", default=False)


class _PrivateParserLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not _READING.get()


# pydicom's warn_and_log also logs raw values. Suppress only records generated
# inside this reader's context; do not disable another thread's library logging.
pydicom.config.logger.addFilter(_PrivateParserLogFilter())


@contextmanager
def _private_parser():
    token = _READING.set(True)
    try:
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            yield captured
    finally:
        _READING.reset(token)


# Explicit allowlist: no names, dates, descriptions, private tags or pixels.
_TAGS = (
    "SOPClassUID", "SOPInstanceUID", "StudyInstanceUID", "SeriesInstanceUID",
    "Modality", "BodyPartExamined", "Laterality", "ImageLaterality",
    "Rows", "Columns", "SamplesPerPixel", "PhotometricInterpretation",
    "BitsAllocated", "BitsStored", "HighBit", "PixelRepresentation",
    "NumberOfFrames", "PixelSpacing", "SliceThickness",
    "ImageOrientationPatient",
)
_MODALITIES = frozenset({"CR", "CT", "DX", "MG", "MR", "NM", "OT", "PT", "RF", "SC", "US", "XA"})
_BODY_REGIONS = frozenset({
    "HEAD", "NECK", "CHEST", "ABDOMEN", "PELVIS", "SPINE", "SHOULDER",
    "ARM", "ELBOW", "FOREARM", "WRIST", "HAND", "HIP", "THIGH", "KNEE",
    "LEG", "ANKLE", "FOOT", "WHOLEBODY",
})
_BODY_ALIASES = {"CSPINE": "CERVICAL_SPINE", "TSPINE": "THORACIC_SPINE", "LSPINE": "LUMBAR_SPINE"}
_PHOTO = frozenset({"MONOCHROME1", "MONOCHROME2", "RGB", "PALETTE COLOR", "YBR_FULL", "YBR_FULL_422", "YBR_PARTIAL_422", "YBR_PARTIAL_420", "YBR_ICT", "YBR_RCT"})
# Initial image-object profile; other IODs need their own requirements.
_SOP_MODALITIES = {
    "1.2.840.10008.5.1.4.1.1.1": {"CR"},
    "1.2.840.10008.5.1.4.1.1.1.1": {"DX"},
    "1.2.840.10008.5.1.4.1.1.1.1.1": {"DX"},
    "1.2.840.10008.5.1.4.1.1.1.2": {"MG"},
    "1.2.840.10008.5.1.4.1.1.1.2.1": {"MG"},
    "1.2.840.10008.5.1.4.1.1.2": {"CT"},
    "1.2.840.10008.5.1.4.1.1.2.1": {"CT"},
    "1.2.840.10008.5.1.4.1.1.4": {"MR"},
    "1.2.840.10008.5.1.4.1.1.4.1": {"MR"},
    "1.2.840.10008.5.1.4.1.1.6.1": {"US"},
    "1.2.840.10008.5.1.4.1.1.7": _MODALITIES,
}
_LONG_VRS = {b"OB", b"OD", b"OF", b"OL", b"OV", b"OW", b"SQ", b"UC", b"UR", b"UT", b"UN"}


class _CorruptMetadata(ValueError):
    pass


class _BoundedFile:
    """Refuse short metadata reads and seeks beyond the physical input."""
    def __init__(self, stream, size: int):
        self.stream, self.size = stream, size

    def read(self, size=-1):
        remaining = self.size - self.tell()
        if remaining == 0:
            return b""
        if size > remaining:
            raise _CorruptMetadata()
        data = self.stream.read(remaining if size < 0 else size)
        if size > 0 and data and len(data) != size:
            raise _CorruptMetadata()
        return data

    def seek(self, offset, whence=0):
        target = offset if whence == 0 else self.tell() + offset if whence == 1 else self.size + offset
        if not 0 <= target <= self.size:
            raise _CorruptMetadata()
        return self.stream.seek(offset, whence)

    def tell(self):
        return self.stream.tell()


def _transfer_syntax_preflight(stream: _BoundedFile) -> str:
    """Check bounded Part 10 file-meta framing before any decompression.

    File meta is always explicit little endian. The rest is parsed by pydicom.
    Deflated datasets are intentionally unsupported to bound memory expansion.
    """
    if len(stream.read(128)) != 128 or stream.read(4) != b"DICM":
        raise _CorruptMetadata()
    transfer = None
    while stream.tell() < min(stream.size, 65536):
        header = stream.read(8)
        if not header:
            break
        group, _element, vr, short_length = struct.unpack("<HH2sH", header)
        if group != 2:
            break
        length = struct.unpack("<I", stream.read(4))[0] if vr in _LONG_VRS else short_length
        if length == 0xFFFFFFFF or stream.tell() + length > min(stream.size, 65536):
            raise _CorruptMetadata()
        if (group, _element) == (2, 0x10):
            transfer = stream.read(length).rstrip(b"\0 ").decode("ascii")
        else:
            stream.seek(length, 1)
    if transfer is None:
        raise _CorruptMetadata()
    return transfer


def _valid_uid(value) -> str | None:
    if not isinstance(value, str) or len(value) > 64 or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", value):
        return None
    if any(len(part) > 1 and part.startswith("0") for part in value.split(".")):
        return None
    return value


def _reference(key: bytes, kind: str, uid: str) -> str:
    return "hmac-sha256:" + hmac.new(key, f"4b-imaging-v1:{kind}:{uid}".encode("ascii"), hashlib.sha256).hexdigest()


class DicomMetadataReader:
    def __init__(self, *, reference_key: bytes, max_file_bytes: int = DEFAULT_MAX_FILE_BYTES):
        if not isinstance(reference_key, bytes) or len(reference_key) < 32:
            raise ValueError("A scoped reference key of at least 32 bytes is required.")
        if type(max_file_bytes) is not int or not 132 <= max_file_bytes <= DEFAULT_MAX_FILE_BYTES:
            raise ValueError("File limit must be between 132 bytes and 64 MiB.")
        self._key = reference_key
        self.max_file_bytes = max_file_bytes

    @staticmethod
    def _failure(code: str) -> DicomMetadataReport:
        return DicomMetadataReport(status="invalid", issues=(MetadataIssue(code, "file", "error"),))

    def read(self, path: str | Path) -> DicomMetadataReport:
        """Read one local regular file. All file/parser failures are sanitized."""
        try:
            # No URL fetching and no symlink/device/FIFO following. Opening a FIFO
            # is non-blocking so fstat can reject it without waiting for a writer.
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as raw:
                info = os.fstat(raw.fileno())
                if not stat.S_ISREG(info.st_mode):
                    return self._failure("local_regular_file_required")
                if info.st_size > self.max_file_bytes:
                    return self._failure("file_size_limit_exceeded")
                stream = _BoundedFile(raw, info.st_size)
                with _private_parser() as parser_warnings:
                    transfer = _transfer_syntax_preflight(stream)
                    syntax = UID(transfer)
                    if (not _valid_uid(transfer) or not syntax.is_transfer_syntax
                            or transfer == "1.2.840.10008.1.2.1.99"):
                        return self._failure("unsupported_transfer_syntax")
                    stream.seek(0)
                    dataset = pydicom.dcmread(stream, force=False, stop_before_pixels=True, specific_tags=list(_TAGS))
                    report = self._extract(dataset)
                    if parser_warnings:
                        return self._failure("dicom_parser_warning")
                    return report
        except OSError:
            return self._failure("local_file_unavailable")
        except Exception:
            # Never include filenames, DICOM values or exception messages.
            return self._failure("invalid_dicom_file")

    def _extract(self, ds) -> DicomMetadataReport:
        issues: list[MetadataIssue] = []

        def issue(code, field, severity="error"):
            issues.append(MetadataIssue(code, field, severity))

        def value(keyword, required=False):
            element = ds.get_item(keyword)
            if element is None or element.value is None or element.value == "":
                if required:
                    issue("missing_required_metadata", keyword, "missing")
                return None
            if hasattr(element, "length") and isinstance(element.value, bytes) and len(element.value) != element.length:
                raise _CorruptMetadata()
            return getattr(ds, keyword)

        def uid(keyword):
            raw = value(keyword, required=True)
            checked = _valid_uid(raw)
            if raw is not None and checked is None:
                issue("invalid_uid", keyword)
            return checked

        study, series, instance, sop = (uid(k) for k in ("StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID", "SOPClassUID"))
        if study and series and instance and len({study, series, instance}) != 3:
            issue("reused_identity_uid", "identity")
        modality = value("Modality", required=True)
        if modality is not None and modality not in _MODALITIES:
            issue("unsupported_modality", "Modality")
            modality = None
        if sop is not None and sop not in _SOP_MODALITIES:
            issue("unsupported_sop_class", "SOPClassUID")
            sop = None
        if sop and modality and modality not in _SOP_MODALITIES[sop]:
            issue("sop_modality_mismatch", "Modality")
        meta = ds.file_meta
        for keyword, expected in (("MediaStorageSOPClassUID", sop), ("MediaStorageSOPInstanceUID", instance)):
            actual = getattr(meta, keyword, None)
            if actual is None:
                issue("missing_required_metadata", keyword, "missing")
            elif _valid_uid(actual) is None or (expected and actual != expected):
                issue("file_meta_identity_mismatch", keyword)

        def integer(keyword, lo, hi, required=True):
            raw = value(keyword, required=required)
            if raw is None:
                return None
            # pydicom IS subclasses int; never coerce decimals/free text/bools.
            if isinstance(raw, bool) or not isinstance(raw, int) or not lo <= raw <= hi:
                issue("invalid_numeric_metadata", keyword)
                return None
            return int(raw)

        def vector(keyword, length, positive=False):
            raw = value(keyword)
            if raw is None:
                return None
            try:
                result = tuple(float(x) for x in raw)
                if len(result) != length or not all(math.isfinite(x) and (not positive or x > 0) for x in result):
                    raise ValueError()
                return result
            except (ValueError, TypeError, OverflowError):
                issue("invalid_numeric_metadata", keyword)
                return None

        rows, columns = integer("Rows", 1, 65535), integer("Columns", 1, 65535)
        samples = integer("SamplesPerPixel", 1, 3)
        allocated = integer("BitsAllocated", 1, 64)
        stored, high = integer("BitsStored", 1, 64), integer("HighBit", 0, 63)
        representation = integer("PixelRepresentation", 0, 1)
        frames = integer("NumberOfFrames", 1, 1000000, required=False)
        photo = value("PhotometricInterpretation", required=True)
        if photo is not None and photo not in _PHOTO:
            issue("unsupported_photometric_interpretation", "PhotometricInterpretation")
            photo = None
        if allocated is not None and allocated not in {1, 8, 16, 32, 64}:
            issue("invalid_bits_allocated", "BitsAllocated")
            allocated = None
        if allocated is not None and stored is not None and stored > allocated:
            issue("inconsistent_bit_depth", "BitsStored")
        if stored is not None and high is not None and high != stored - 1:
            issue("inconsistent_high_bit", "HighBit")
        if samples is not None and photo is not None:
            expected_samples = 1 if photo in {"MONOCHROME1", "MONOCHROME2", "PALETTE COLOR"} else 3
            if samples != expected_samples:
                issue("inconsistent_color_samples", "SamplesPerPixel")
        spacing = vector("PixelSpacing", 2, positive=True)
        orientation = vector("ImageOrientationPatient", 6)
        if orientation:
            row, col = orientation[:3], orientation[3:]
            if (any(abs(sum(x*x for x in axis) - 1) > 1e-3 for axis in (row, col))
                    or abs(sum(a*b for a, b in zip(row, col))) > 1e-3):
                issue("invalid_orientation", "ImageOrientationPatient")
                orientation = None
        thickness = value("SliceThickness")
        if thickness is not None:
            try:
                thickness = float(thickness)
                if not math.isfinite(thickness) or thickness <= 0:
                    raise ValueError()
            except (ValueError, TypeError, OverflowError):
                issue("invalid_numeric_metadata", "SliceThickness")
                thickness = None
        body = value("BodyPartExamined")
        if body is not None:
            if body in _BODY_ALIASES:
                body = _BODY_ALIASES[body]
            elif body not in _BODY_REGIONS:
                issue("unsupported_body_region", "BodyPartExamined")
                body = None
        laterality, image_laterality = value("Laterality"), value("ImageLaterality")
        for field, item in (("Laterality", laterality), ("ImageLaterality", image_laterality)):
            allowed = {"L", "R"} if field == "Laterality" else {"L", "R", "B", "U"}
            if item is not None and item not in allowed:
                issue("invalid_laterality", field)
        if laterality and image_laterality and laterality != image_laterality:
            issue("inconsistent_laterality", "Laterality")
        side = image_laterality or laterality
        side = side if side in {"L", "R", "B", "U"} else None
        technical = TechnicalMetadata(
            sop_class_uid=sop, transfer_syntax_uid=str(meta.TransferSyntaxUID),
            rows=rows, columns=columns, samples_per_pixel=samples,
            photometric_interpretation=photo, bits_allocated=allocated,
            bits_stored=stored, high_bit=high, pixel_representation=representation,
            number_of_frames=frames, pixel_spacing=spacing,
            slice_thickness=thickness, image_orientation_patient=orientation,
        )
        status = "invalid" if any(i.severity == "error" for i in issues) else "incomplete" if issues else "valid"
        return DicomMetadataReport(
            status=status, modality=modality,
            study_reference=_reference(self._key, "study", study) if study else None,
            series_reference=_reference(self._key, "series", series) if series else None,
            instance_reference=_reference(self._key, "instance", instance) if instance else None,
            body_region=body, laterality=side, technical=technical, issues=tuple(issues),
        )
