"""Database-free reader tests; all file contents are generated synthetically."""

from __future__ import annotations

from contextlib import contextmanager
from io import BytesIO, StringIO
import json
import logging
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import warnings

import pydicom

from backend.app.imaging_intelligence.reader import DicomMetadataReader, _BoundedFile
from backend.tests.imaging_intelligence.synthetic_dicom import (
    IDENTIFYING_MARKERS,
    SYNTHETIC_INSTANCE_UID,
    SYNTHETIC_SERIES_UID,
    SYNTHETIC_STUDY_UID,
    write_synthetic_dicom,
)


REFERENCE_KEY = b"synthetic-test-key-32-bytes-long!!"


@contextmanager
def captured_parser_output():
    output = StringIO()
    handler = logging.StreamHandler(output)
    pydicom.config.logger.addHandler(handler)
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            yield output, caught
    finally:
        pydicom.config.logger.removeHandler(handler)


class DicomMetadataReaderTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "SYNTHETIC-PATIENT-FILENAME.dcm"
        self.reader = DicomMetadataReader(reference_key=REFERENCE_KEY)

    def read_fixture(self, *, modality="CT", overrides=None, omit=()):
        # Fixture generation may correctly warn about deliberately malformed VRs;
        # the privacy assertions concern the production reader's output only.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            write_synthetic_dicom(self.path, modality, overrides=overrides, omit=omit)
        return self.reader.read(self.path)

    def assert_issue(self, report, code, field=None):
        self.assertIn(code, {issue.code for issue in report.issues})
        if field:
            self.assertIn((code, field), {(i.code, i.field) for i in report.issues})

    def assert_private(self, report):
        serialized = report.to_json()
        for marker in (*IDENTIFYING_MARKERS, SYNTHETIC_STUDY_UID,
                       SYNTHETIC_SERIES_UID, SYNTHETIC_INSTANCE_UID,
                       self.path.name, str(self.path.parent)):
            self.assertNotIn(marker, serialized)

    def test_healthy_ct_and_mr_have_structured_technical_metadata(self):
        for modality in ("CT", "MR"):
            with self.subTest(modality=modality):
                report = self.read_fixture(modality=modality)
                self.assertEqual(report.status, "valid")
                self.assertEqual(report.modality, modality)
                self.assertEqual(report.body_region, "KNEE")
                self.assertEqual(report.laterality, "R")
                self.assertEqual(report.technical.rows, 2)
                self.assertEqual(report.technical.columns, 3)
                self.assertEqual(report.technical.bits_stored, 12)
                self.assertEqual(report.technical.pixel_spacing, (0.5, 0.5))
                self.assertEqual(report.issues, ())
                self.assertFalse(report.pixel_data_validated)
                self.assertFalse(report.dicom_identity_verified)
                self.assertTrue(report.study_reference.startswith("hmac-sha256:"))
                self.assertEqual(json.loads(report.to_json()), report.to_dict())
                self.assert_private(report)

    def test_incomplete_metadata_retains_valid_available_fields(self):
        report = self.read_fixture(omit=("StudyInstanceUID", "Rows", "PixelRepresentation"))
        self.assertEqual(report.status, "incomplete")
        self.assertIsNone(report.study_reference)
        self.assertIsNotNone(report.series_reference)
        self.assertEqual(report.technical.columns, 3)
        for field in ("StudyInstanceUID", "Rows", "PixelRepresentation"):
            self.assert_issue(report, "missing_required_metadata", field)
        self.assert_private(report)

    def test_hmac_is_deterministic_key_scoped_and_identity_scoped(self):
        first = self.read_fixture()
        repeat = self.reader.read(self.path)
        alternate = DicomMetadataReader(reference_key=b"another-distinct-key-32-bytes-long!").read(self.path)
        self.assertEqual(first.to_dict(), repeat.to_dict())
        self.assertEqual(first.metadata_sha256, repeat.metadata_sha256)
        for field in ("study_reference", "series_reference", "instance_reference"):
            self.assertNotEqual(getattr(first, field), getattr(alternate, field))
        same_identity = self.read_fixture(overrides={"SeriesInstanceUID": SYNTHETIC_STUDY_UID})
        self.assertNotEqual(same_identity.study_reference, same_identity.series_reference)
        self.assert_issue(same_identity, "reused_identity_uid")

    def test_invalid_uids_are_sanitized_without_parser_warnings_or_logs(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            write_synthetic_dicom(self.path, overrides={"StudyInstanceUID": "SYNTHETIC-PATIENT-UID-SECRET"})
        with captured_parser_output() as (logs, caught):
            report = self.reader.read(self.path)
        self.assertEqual(report.status, "invalid")
        self.assertIsNone(report.study_reference)
        self.assertEqual(logs.getvalue(), "")
        self.assertEqual(caught, [])
        self.assertNotIn("SYNTHETIC-PATIENT-UID-SECRET", report.to_json())
        self.assert_private(report)

    def test_free_text_in_allowlisted_coded_fields_cannot_escape(self):
        report = self.read_fixture(overrides={
            "BodyPartExamined": "PRIVATE PATIENT SECRET",
            "Modality": "PRIVATE PATIENT SECRET",
            "PhotometricInterpretation": "PRIVATE PATIENT SECRET",
            "Laterality": "PRIVATE PATIENT SECRET",
            "ImageLaterality": "PRIVATE PATIENT SECRET",
        })
        self.assertEqual(report.status, "invalid")
        self.assertNotIn("PRIVATE PATIENT SECRET", report.to_json())
        self.assertIsNone(report.body_region)
        self.assertIsNone(report.modality)
        self.assertIsNone(report.laterality)
        self.assertIsNone(report.technical.photometric_interpretation)

    def test_non_dicom_and_truncated_headers_are_invalid_and_private(self):
        for data in (b"", b"synthetic corrupt patient secret", b"\0" * 128 + b"DICM", b"\0" * 128 + b"DICM\x02\x00"):
            with self.subTest(size=len(data)):
                self.path.write_bytes(data)
                with captured_parser_output() as (logs, caught):
                    report = self.reader.read(self.path)
                self.assertEqual(report.status, "invalid")
                self.assertEqual(logs.getvalue(), "")
                self.assertEqual(caught, [])
                self.assert_private(report)

    def test_truncated_metadata_and_trailing_partial_element_are_invalid(self):
        write_synthetic_dicom(self.path, omit=("PixelData",))
        full = self.path.read_bytes()
        for data in (full[:-1], full + b"\x40\x00\x00", full + struct.pack("<HH2sH", 0x0040, 0xA160, b"UT", 0) + struct.pack("<I", 200) + b"SYNTHETIC SECRET"):
            with self.subTest(size=len(data)):
                self.path.write_bytes(data)
                with captured_parser_output() as (logs, caught):
                    report = self.reader.read(self.path)
                self.assertEqual(report.status, "invalid")
                self.assertEqual(logs.getvalue(), "")
                self.assertEqual(caught, [])
                self.assert_private(report)

    def test_numeric_bit_depth_spacing_and_orientation_inconsistencies(self):
        cases = (
            ({"Rows": 0}, "invalid_numeric_metadata", "Rows"),
            ({"Columns": 0}, "invalid_numeric_metadata", "Columns"),
            ({"BitsAllocated": 12}, "invalid_bits_allocated", "BitsAllocated"),
            ({"BitsAllocated": 8, "BitsStored": 12}, "inconsistent_bit_depth", "BitsStored"),
            ({"HighBit": 15}, "inconsistent_high_bit", "HighBit"),
            ({"PixelRepresentation": 2}, "invalid_numeric_metadata", "PixelRepresentation"),
            ({"NumberOfFrames": 0}, "invalid_numeric_metadata", "NumberOfFrames"),
            ({"PixelSpacing": [-1, 0.5]}, "invalid_numeric_metadata", "PixelSpacing"),
            ({"PixelSpacing": [0, 0.5]}, "invalid_numeric_metadata", "PixelSpacing"),
            ({"PixelSpacing": [float("nan"), 0.5]}, "invalid_numeric_metadata", "PixelSpacing"),
            ({"PixelSpacing": [float("inf"), 0.5]}, "invalid_numeric_metadata", "PixelSpacing"),
            ({"PixelSpacing": [0.5]}, "invalid_numeric_metadata", "PixelSpacing"),
            ({"SliceThickness": float("nan")}, "invalid_numeric_metadata", "SliceThickness"),
            ({"SliceThickness": -1}, "invalid_numeric_metadata", "SliceThickness"),
            ({"ImageOrientationPatient": [1, 0, 0, 1, 0, 0]}, "invalid_orientation", "ImageOrientationPatient"),
            ({"ImageOrientationPatient": [2, 0, 0, 0, 1, 0]}, "invalid_orientation", "ImageOrientationPatient"),
            ({"ImageOrientationPatient": [float("nan"), 0, 0, 0, 1, 0]}, "invalid_numeric_metadata", "ImageOrientationPatient"),
            ({"SamplesPerPixel": 3}, "inconsistent_color_samples", "SamplesPerPixel"),
            ({"PhotometricInterpretation": "RGB"}, "inconsistent_color_samples", "SamplesPerPixel"),
            ({"ImageLaterality": "L"}, "inconsistent_laterality", "Laterality"),
            ({"Modality": "MR"}, "sop_modality_mismatch", "Modality"),
        )
        for overrides, code, field in cases:
            with self.subTest(overrides=overrides):
                report = self.read_fixture(overrides=overrides)
                self.assertEqual(report.status, "invalid")
                self.assert_issue(report, code, field)
                self.assert_private(report)
                # No nonfinite JSON can leave the metadata contract.
                self.assertNotIn("NaN", report.to_json())
                self.assertNotIn("Infinity", report.to_json())

    def test_file_meta_uid_mismatch_is_rejected(self):
        write_synthetic_dicom(self.path)
        data = self.path.read_bytes()
        old = SYNTHETIC_INSTANCE_UID.encode("ascii")
        changed = old[:-1] + b"9"
        self.assertGreaterEqual(data.count(old), 2)
        self.path.write_bytes(data.replace(old, changed, 1))
        report = self.reader.read(self.path)
        self.assertEqual(report.status, "invalid")
        self.assert_issue(report, "file_meta_identity_mismatch", "MediaStorageSOPInstanceUID")
        self.assert_private(report)

    def test_invalid_uid_format_leading_zero_is_not_exported(self):
        report = self.read_fixture(overrides={"StudyInstanceUID": "1.2.03.4"})
        self.assertEqual(report.status, "invalid")
        self.assertIsNone(report.study_reference)
        self.assertNotIn("1.2.03.4", report.to_json())

    def test_series_laterality_rejects_bilateral_and_unpaired_image_codes(self):
        for side in ("B", "U"):
            with self.subTest(series_laterality=side):
                report = self.read_fixture(overrides={"Laterality": side, "ImageLaterality": side})
                self.assertEqual(report.status, "invalid")
                self.assert_issue(report, "invalid_laterality", "Laterality")

    def test_image_laterality_supports_bilateral_and_unpaired_without_series_side(self):
        for side in ("B", "U"):
            with self.subTest(image_laterality=side):
                report = self.read_fixture(overrides={"ImageLaterality": side}, omit=("Laterality",))
                self.assertEqual(report.status, "valid")
                self.assertEqual(report.laterality, side)

    def test_transfer_syntax_claim_disagrees_with_dataset_encoding(self):
        write_synthetic_dicom(self.path)
        data = self.path.read_bytes()
        old_value = b"1.2.840.10008.1.2.1\0"
        new_value = b"1.2.840.10008.1.2\0"
        old_tag = struct.pack("<HH2sH", 2, 0x10, b"UI", len(old_value))
        new_tag = struct.pack("<HH2sH", 2, 0x10, b"UI", len(new_value))
        self.assertIn(old_tag + old_value, data)
        data = bytearray(data.replace(old_tag + old_value, new_tag + new_value, 1))
        # Keep file-meta group length correct; only the encoding claim is false.
        group_length = struct.unpack_from("<I", data, 140)[0]
        struct.pack_into("<I", data, 140, group_length + len(new_value) - len(old_value))
        self.path.write_bytes(data)
        with captured_parser_output() as (logs, caught):
            report = self.reader.read(self.path)
        self.assertEqual(report.status, "invalid")
        self.assertEqual(logs.getvalue(), "")
        self.assertEqual(caught, [])
        self.assert_private(report)

    def test_file_bounds_missing_file_directory_symlink_and_fifo(self):
        write_synthetic_dicom(self.path)
        limited = DicomMetadataReader(reference_key=REFERENCE_KEY, max_file_bytes=132)
        self.assert_issue(limited.read(self.path), "file_size_limit_exceeded")
        self.assert_issue(self.reader.read(self.path.with_name("missing.dcm")), "local_file_unavailable")
        self.assertEqual(self.reader.read(self.path.parent).status, "invalid")
        link = self.path.with_name("symlink.dcm")
        link.symlink_to(self.path)
        self.assertEqual(self.reader.read(link).status, "invalid")
        fifo = self.path.with_name("fifo.dcm")
        os.mkfifo(fifo)
        self.assert_issue(self.reader.read(fifo), "local_regular_file_required")

    def test_url_is_not_fetched(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("network access forbidden")):
            report = self.reader.read("https://synthetic-imaging.invalid/patient-secret.dcm")
        self.assertEqual(report.status, "invalid")
        self.assertNotIn("patient-secret", report.to_json())

    def test_deflated_transfer_syntax_rejected_before_parser_or_decompress(self):
        write_synthetic_dicom(self.path)
        data = self.path.read_bytes()
        # Replace the file-meta transfer syntax element, preserving correct VR
        # framing; the remaining dataset need not be compressed to reject it.
        original = b"1.2.840.10008.1.2.1\0"
        replacement = b"1.2.840.10008.1.2.1.99\0"
        tag = struct.pack("<HH2sH", 2, 0x10, b"UI", len(original))
        changed_tag = struct.pack("<HH2sH", 2, 0x10, b"UI", len(replacement))
        self.assertIn(tag + original, data)
        self.path.write_bytes(data.replace(tag + original, changed_tag + replacement, 1))
        with patch("pydicom.dcmread", side_effect=AssertionError("parser must not run")), patch("zlib.decompress", side_effect=AssertionError("decompression forbidden")):
            report = self.reader.read(self.path)
        self.assertEqual(report.status, "invalid")
        self.assert_issue(report, "unsupported_transfer_syntax")

    def test_reader_configuration_is_bounded_and_secret_key_is_required(self):
        for key in (b"", b"too-short", "x" * 32, None):
            with self.subTest(key_type=type(key).__name__):
                with self.assertRaises(ValueError):
                    DicomMetadataReader(reference_key=key)
        for limit in (131, 64 * 1024 * 1024 + 1, True, 200.0):
            with self.subTest(limit=limit):
                with self.assertRaises(ValueError):
                    DicomMetadataReader(reference_key=REFERENCE_KEY, max_file_bytes=limit)

    def test_declared_huge_value_is_rejected_before_underlying_allocation(self):
        class AllocationGuard(BytesIO):
            def read(self, size=-1):
                if size > 1024:
                    raise AssertionError("Untrusted DICOM length reached the allocator")
                return super().read(size)

        stream = _BoundedFile(AllocationGuard(b"synthetic"), 9)
        with self.assertRaises(ValueError):
            stream.read(0xFFFFFFFE)

    def test_report_digest_changes_with_technical_metadata(self):
        first = self.read_fixture()
        changed = self.read_fixture(overrides={"Rows": 3})
        self.assertNotEqual(first.metadata_sha256, changed.metadata_sha256)
        self.assertEqual(first.study_reference, changed.study_reference)


if __name__ == "__main__":
    unittest.main()
