from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

try:
    import numpy as np
    import pydicom
    from vtkmodules.vtkFiltersGeneral import vtkDiscreteFlyingEdges3D
except (ImportError, OSError):
    raise unittest.SkipTest("The optional CPython 3.12 imaging-3d runtime is required.") from None

from backend.app.imaging_intelligence.reconstruction import (
    MAX_INSTANCE_BYTES, ReconstructedVolume, SyntheticVolumeReconstructor, VolumeReconstructionError,
)
from backend.app.imaging_intelligence.surface_reconstruction import reconstruct_surfaces
from backend.tools.imaging_metadata_demo import SYNTHETIC_REFERENCE_KEY
from backend.tools.synthetic_knee_fixture import analytic_knee, generate_knee_dicom


class VolumeTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.directory = Path(self.folder.name)
        self.reader = SyntheticVolumeReconstructor(reference_key=SYNTHETIC_REFERENCE_KEY)

    def fixture(self, **kwargs):
        return generate_knee_dicom(self.directory, size=32, **kwargs)

    def edit(self, source, index=0, **values):
        instance = source.instances[index]
        ds = pydicom.dcmread(instance.path)
        for key, value in values.items():
            setattr(ds, key, value)
        ds.save_as(instance.path, enforce_file_format=True)
        revised = replace(instance, file_sha256=hashlib.sha256(instance.path.read_bytes()).hexdigest())
        items = list(source.instances)
        items[index] = revised
        return replace(source, instances=tuple(items))

    def test_mr_and_signed_ct_pixel_roundtrip(self):
        for modality in ("MR", "CT"):
            with self.subTest(modality=modality):
                fixture = self.fixture(modality=modality)
                volume = self.reader.reconstruct(fixture.source)
                np.testing.assert_array_equal(volume.voxels, fixture.expected_values)
                self.assertEqual(set(np.unique(fixture.labels)), set(range(9)))
                self.assertEqual(volume.voxels.dtype, np.dtype("<f4"))
                self.assertEqual(volume.voxels.min() < 0, modality == "CT")
                self.assertFalse(volume.voxels.flags.writeable)
                self.assertFalse(volume.affine_lps.flags.writeable)

    def test_file_order_has_no_effect_on_voxels_or_provenance(self):
        source = self.fixture().source
        first = self.reader.reconstruct(source)
        second = self.reader.reconstruct(replace(source, instances=tuple(reversed(source.instances))))
        np.testing.assert_array_equal(first.voxels, second.voxels)
        self.assertEqual(first.to_manifest(), second.to_manifest())

    def test_anisotropic_oblique_affine_preserves_ijk_to_lps(self):
        a = 2**-.5
        fixture = self.fixture(spacing_xyz=(.7, 1.1, 1.8), orientation=(a, a, 0, -a, a, 0))
        volume = self.reader.reconstruct(fixture.source)
        expected_linear = np.array([[a*.7, -a*1.1, 0], [a*.7, a*1.1, 0], [0, 0, 1.8]])
        np.testing.assert_allclose(volume.affine_lps[:3, :3], expected_linear, atol=1e-10)
        expected_point = expected_linear @ (np.array([4, 9, 17])-15.5)
        np.testing.assert_allclose((volume.affine_lps @ [4, 9, 17, 1])[:3], expected_point, atol=1e-10)

    def test_slice_thickness_is_not_used_as_inter_slice_distance(self):
        source = self.fixture().source
        source = self.edit(source, SliceThickness=8)
        volume = self.reader.reconstruct(source)
        self.assertAlmostEqual(np.linalg.norm(volume.affine_lps[:3, 2]), 1.4)

    def test_rescale_is_applied_to_actual_stored_pixels(self):
        fixture = self.fixture()
        source = self.edit(fixture.source, RescaleSlope=2, RescaleIntercept=-100)
        volume = self.reader.reconstruct(source)
        np.testing.assert_array_equal(volume.voxels[0], fixture.expected_values[0]*2-100)
        np.testing.assert_array_equal(volume.voxels[1:], fixture.expected_values[1:])

    def test_changed_file_bytes_fail_before_use(self):
        source = self.fixture().source
        source.instances[0].path.write_bytes(b"private filename or patient data must never escape")
        with self.assertRaisesRegex(VolumeReconstructionError, "^synthetic_file_hash_mismatch$"):
            self.reader.reconstruct(source)

    def test_duplicate_missing_and_broken_geometry_are_blocked(self):
        source = self.fixture().source
        cases = (replace(source, instances=source.instances[:-1]),
                 replace(source, instances=(source.instances[0],)*32),
                 self.edit(source, ImagePositionPatient=[0, 0, 100]))
        for candidate in cases:
            with self.subTest(case=len(candidate.instances)), self.assertRaises(VolumeReconstructionError):
                self.reader.reconstruct(candidate)

    def test_fixture_marker_and_grid_mismatch_are_blocked(self):
        source = self.fixture().source
        with self.assertRaisesRegex(VolumeReconstructionError, "^synthetic_fixture_marker_required$"):
            self.reader.reconstruct(self.edit(source, PatientID="NEVER_EXPORT_PATIENT_MARKER"))
        source = self.fixture().source
        affine = np.asarray(source.affine_lps)
        affine[0, 3] += 2
        with self.assertRaisesRegex(VolumeReconstructionError, "^synthetic_label_grid_mismatch$"):
            self.reader.reconstruct(replace(source, affine_lps=tuple(map(tuple, affine))))

    def test_nonfinite_rescale_and_unsupported_profile_are_blocked(self):
        source = self.fixture().source
        with self.assertRaises(VolumeReconstructionError):
            self.reader.reconstruct(self.edit(source, RescaleSlope=0))
        source = self.fixture().source
        with self.assertRaises(VolumeReconstructionError):
            self.reader.reconstruct(self.edit(source, NumberOfFrames=2))

    def test_truncated_pixels_even_with_rehashed_inventory_are_blocked(self):
        source = self.fixture().source
        source = self.edit(source, PixelData=b"\0"*10)
        with self.assertRaisesRegex(VolumeReconstructionError, "^unsupported_synthetic_pixel_profile$"):
            self.reader.reconstruct(source)

    def test_size_limits_symlinks_and_fifos_fail_without_blocking(self):
        source = self.fixture().source
        instance = source.instances[0]
        large = self.directory/"large.dcm"
        large.write_bytes(b"x"*(MAX_INSTANCE_BYTES+1))
        link = self.directory/"symlink.dcm"
        link.symlink_to(instance.path)
        fifo = self.directory/"fifo.dcm"
        os.mkfifo(fifo)
        for path in (large, link, fifo):
            with self.subTest(path=path.name), self.assertRaises(VolumeReconstructionError):
                self.reader.reconstruct(replace(source, instances=(replace(instance,path=path),)+source.instances[1:]))

    def test_manifest_never_contains_raw_uid_identity_or_local_path(self):
        volume = self.reader.reconstruct(self.fixture().source)
        payload = json.dumps(volume.to_manifest(), allow_nan=False)
        for secret in (str(self.directory), "SYNTHETIC^KNEE_ONLY", "4B-SYNTHETIC-KNEE-V1", "1.2.826.0.1.3680043"):
            self.assertNotIn(secret, payload)
        self.assertFalse(volume.to_manifest()["is_clinically_validated"])


class SurfaceTests(unittest.TestCase):
    def volume(self):
        affine = np.array([[0, -3, 0, 10], [2, 0, 0, 20], [0, 0, 4, 30], [0, 0, 0, 1]], dtype=float)
        return ReconstructedVolume(np.zeros((8, 8, 8)), affine, "MR", "a"*64,
                                   tuple(f"hmac-sha256:{i:064x}" for i in range(8)))

    def labels(self):
        labels = np.zeros((8,8,8),dtype=np.uint8)
        labels[2:4,2:5,1:3] = 1
        labels[5:7,5:7,5:7] = 2
        return labels

    def test_vtk_surface_has_correct_physical_bounds_and_reference_volume(self):
        output = reconstruct_surfaces(self.volume(), self.labels(), label_codes=(1,2))
        mesh = output["meshes"][0]
        # Label 1 has i=[1,2],j=[2,4],k=[2,3]; its boundary lies half a voxel out.
        np.testing.assert_allclose(mesh["bounds_lps_mm"], [[-3.5,21,36], [5.5,25,44]])
        self.assertAlmostEqual(mesh["voxel_volume_mm3"], 12*2*3*4)
        self.assertGreater(mesh["surface_area_mm2"], 0)
        self.assertEqual(output["label_source"],"analytic_synthetic_ground_truth")
        self.assertFalse(output["smoothing_applied"])
        self.assertFalse(output["is_clinically_validated"])

    def test_surface_topology_is_indexed_finite_and_deterministic(self):
        first = reconstruct_surfaces(self.volume(), self.labels(), label_codes=(1,2))
        second = reconstruct_surfaces(self.volume(), self.labels(), label_codes=(1,2))
        self.assertEqual(first,second)
        for mesh in first["meshes"]:
            vertices, faces = np.asarray(mesh["vertices_lps_mm"]), np.asarray(mesh["triangles"])
            self.assertTrue(np.isfinite(vertices).all())
            self.assertTrue(np.all(faces >= 0) and np.all(faces < len(vertices)))
            # Every edge of a closed binary label surface has two incident faces.
            edges = np.sort(np.concatenate([faces[:,[0,1]],faces[:,[1,2]],faces[:,[2,0]]]),axis=1)
            _, count = np.unique(edges,axis=0,return_counts=True)
            self.assertTrue(np.all(count==2))

    def test_misaligned_unknown_or_boundary_clipped_labels_fail(self):
        labels = self.labels()
        for bad in (labels[:-1],labels.astype(float),np.where(labels==2,3,labels).astype(np.uint8)):
            with self.assertRaises(ValueError):
                reconstruct_surfaces(self.volume(),bad,label_codes=(1,2))
        labels[0,2,2]=1
        with self.assertRaises(ValueError):
            reconstruct_surfaces(self.volume(),labels,label_codes=(1,2))

    def test_phantom_is_deterministic_and_has_no_boundary_labels(self):
        for modality in ("MR","CT"):
            labels,values = analytic_knee(64,modality)
            other,again = analytic_knee(64,modality)
            np.testing.assert_array_equal(labels,other)
            np.testing.assert_array_equal(values,again)
            self.assertEqual(set(np.unique(labels)),set(range(9)))
            self.assertFalse(labels[0].any() or labels[-1].any())


if __name__ == '__main__':
    unittest.main()
