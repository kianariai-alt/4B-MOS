from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pydicom

from backend.app.imaging_intelligence.series import ExpectedSeries, SeriesMetadataReader, StudySeriesValidator
from backend.tools.imaging_metadata_demo import SYNTHETIC_REFERENCE_KEY
from backend.tools.imaging_series_demo import generate_synthetic_series, run_series_demo


class SeriesValidationTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.fixture = generate_synthetic_series(Path(folder.name))
        self.reader = SeriesMetadataReader(reference_key=SYNTHETIC_REFERENCE_KEY)
        self.validator = StudySeriesValidator(self.reader)

    def items(self):
        return tuple(self.reader.read(p) for p in self.fixture.files)

    def result(self, items=None, expected=True):
        return self.validator.validate(self.items() if items is None else items,
                                       expected=(self.fixture.expected,) if expected else ())

    def edit(self, index, **values):
        path = self.fixture.files[index]
        dataset = pydicom.dcmread(path)
        for name, value in values.items():
            if value is None:
                delattr(dataset, name)
            else:
                setattr(dataset, name, value)
        dataset.save_as(path, enforce_file_format=True)

    def test_complete_manifest_and_geometry_have_deterministic_order(self):
        result = self.result()
        self.assertEqual(result.status, "valid")
        series = result.series[0]
        self.assertEqual(series.ordered_instance_references, self.fixture.expected.instance_references)
        self.assertEqual(series.slice_step_mm, 3)
        self.assertEqual(series.completeness, "expected_manifest_matched")
        reverse = self.result(tuple(reversed(self.items())))
        self.assertEqual(result.to_dict(), reverse.to_dict())
        self.assertFalse(series.pixel_data_validated)
        self.assertFalse(series.dicom_identity_verified)

    def test_uniform_spacing_alone_does_not_prove_completeness(self):
        result = self.result(expected=False)
        self.assertEqual(result.status, "valid")
        self.assertEqual(result.series[0].completeness, "not_established")
        self.assertIsNone(result.series[0].expected_inventory_sha256)

    def test_expected_missing_slice_is_incomplete_even_with_uniform_spacing(self):
        result = self.result(self.items()[1:])
        self.assertEqual(result.status, "incomplete")
        self.assertIn("expected_instances_mismatch", result.series[0].issues)

    def test_duplicate_and_conflicting_instances_are_rejected(self):
        items = self.items()
        result = self.result(items + items[:1])
        self.assertEqual(result.status, "invalid")
        self.assertIn("duplicate_instance", result.issues)
        altered = replace(items[0], geometry=replace(items[0].geometry, instance_number=99))
        self.assertIn("conflicting_duplicate_instance", self.result(items + (altered,)).issues)

    def test_mixed_studies_and_reused_series_uid_are_rejected(self):
        self.edit(1, StudyInstanceUID="1.2.826.0.1.3680043.10.543.9999")
        result = self.result()
        self.assertEqual(result.status, "invalid")
        self.assertIn("mixed_studies", result.issues)
        self.assertIn("series_reused_across_studies", result.issues)

    def test_multiple_series_are_grouped_and_unexpected_series_are_reported(self):
        self.edit(1, SeriesInstanceUID="1.2.826.0.1.3680043.10.543.8888")
        result = self.result()
        self.assertEqual(len(result.series), 2)
        self.assertIn("unexpected_series", result.issues)
        self.assertEqual(result.status, "incomplete")

    def test_dimensions_pixel_spacing_and_orientation_disagreement(self):
        items = self.items()
        for field, value, expected in (("rows", 8, "inconsistent_rows"),
                                       ("pixel_spacing", (1., 1.), "inconsistent_pixel_spacing"),
                                       ("image_orientation_patient", (0., 1., 0., 1., 0., 0.), "inconsistent_image_orientation_patient")):
            with self.subTest(field=field):
                metadata = replace(items[1].metadata, technical=replace(items[1].metadata.technical, **{field:value}))
                result = self.result((items[0], replace(items[1], metadata=metadata), items[2]))
                self.assertEqual(result.status, "invalid")
                self.assertIn(expected, result.series[0].issues)

    def test_frame_of_reference_must_match(self):
        self.edit(1, FrameOfReferenceUID="1.2.826.0.1.3680043.10.543.7777")
        result = self.result()
        self.assertEqual(result.status, "invalid")
        self.assertIn("inconsistent_frame_reference", result.series[0].issues)

    def test_missing_geometry_does_not_get_invented(self):
        self.edit(1, ImagePositionPatient=None, FrameOfReferenceUID=None)
        result = self.result()
        self.assertEqual(result.status, "incomplete")
        self.assertIn("missing_image_position", result.series[0].issues)
        self.assertEqual(result.series[0].ordered_instance_references, ())

    def test_geometry_projection_handles_oblique_and_descending_input(self):
        for index in range(3):
            self.edit(index, ImageOrientationPatient=[0, 1, 0, 0, 0, 1], ImagePositionPatient=[index*3, 0, 0])
        result = self.result(tuple(reversed(self.items())))
        self.assertEqual(result.status, "valid")
        self.assertEqual(result.series[0].ordered_instance_references, self.fixture.expected.instance_references)

    def test_repeated_planes_and_nonuniform_spacing_block_volume_profile(self):
        self.edit(1, ImagePositionPatient=[0, 0, 0])
        self.assertIn("repeated_slice_position", self.result().series[0].issues)
        self.edit(1, ImagePositionPatient=[0, 0, 2])
        result = self.result()
        self.assertEqual(result.status, "incomplete")
        self.assertIn("non_uniform_slice_spacing", result.series[0].issues)

    def test_declared_spacing_mismatch_and_number_gap_are_hints(self):
        self.edit(2, SpacingBetweenSlices=9, InstanceNumber=7)
        result = self.result()
        self.assertEqual(result.status, "incomplete")
        self.assertIn("declared_slice_spacing_mismatch", result.series[0].issues)
        self.assertIn("instance_number_gap_hint", result.series[0].issues)

    def test_multiframe_geometry_is_not_silently_treated_as_one_slice(self):
        self.edit(1, NumberOfFrames=2)
        result = self.result()
        self.assertEqual(result.status, "incomplete")
        self.assertIn("multiframe_geometry_not_supported", {i.code for i in self.items()[1].issues})

    def test_nan_image_position_fails_closed(self):
        self.edit(1, ImagePositionPatient=[float('nan'), 0, 0])
        self.assertEqual(self.result().status, "invalid")
        self.assertNotIn("NaN", json.dumps(self.result().to_dict(), allow_nan=False))

    def test_empty_corrupt_and_limits(self):
        self.assertEqual(self.validator.validate(()).status, "incomplete")
        self.fixture.files[0].write_bytes(b"synthetic corrupt")
        self.assertEqual(self.result().status, "invalid")
        limited = StudySeriesValidator(self.reader, max_instances=2)
        self.assertEqual(limited.read(self.fixture.files).issues, ("instance_limit_exceeded",))

    def test_invalid_expected_manifest_is_rejected(self):
        for references in ((), ("1.2.3",), self.fixture.expected.instance_references * 2):
            with self.assertRaises(ValueError):
                ExpectedSeries(self.fixture.expected.series_reference, references)
        with self.assertRaises(ValueError):
            self.validator.validate(self.items(), expected=(self.fixture.expected, self.fixture.expected))

    def test_no_patient_uid_filename_or_frame_uid_is_exported(self):
        payload = json.dumps(self.result().to_dict())
        for value in ("SYNTHETIC^DEMO_ONLY", "SYNTHETIC-DEMO-ID", "1.2.826.0.1.3680043", str(self.fixture.files[0])):
            self.assertNotIn(value, payload)

    def test_end_to_end_scenarios(self):
        result = run_series_demo()
        self.assertEqual(result, run_series_demo())
        self.assertEqual(result["complete"]["status"], "valid")
        self.assertEqual(result["missing_slice"]["status"], "incomplete")
        self.assertEqual(result["duplicate_instance"]["status"], "invalid")


if __name__ == '__main__':
    unittest.main()
