"""VTK surfaces from explicit synthetic ground-truth labels; no image segmentation."""

import hashlib

import numpy as np

from .models import canonical_digest
from .reconstruction import ReconstructedVolume


def reconstruct_surfaces(volume: ReconstructedVolume, labels: np.ndarray, *, label_codes: tuple[int, ...]):
    """Half-voxel label boundaries, transformed into the source LPS frame.

    No smoothing, learned detail, resampling or anatomical inference is applied.
    The binary mask grid must be the caller-owned ground truth for this fixture.
    """
    if (type(volume) is not ReconstructedVolume or not isinstance(labels, np.ndarray)
            or labels.shape != volume.voxels.shape or labels.dtype != np.uint8
            or type(label_codes) is not tuple or not 1 <= len(label_codes) <= 16
            or any(type(x) is not int or not 1 <= x <= 255 for x in label_codes)
            or len(set(label_codes)) != len(label_codes)
            or set(np.unique(labels)) != {0, *label_codes}
            or any(np.any(face) for face in (labels[0], labels[-1], labels[:, 0], labels[:, -1],
                                             labels[:, :, 0], labels[:, :, -1]))):
        raise ValueError("Invalid or boundary-clipped synthetic label volume.")
    from vtkmodules.vtkCommonDataModel import vtkImageData
    from vtkmodules.vtkFiltersGeneral import vtkDiscreteFlyingEdges3D
    from vtkmodules.util.numpy_support import numpy_to_vtk, vtk_to_numpy
    from vtkmodules.vtkCommonCore import vtkVersion

    image = vtkImageData()
    image.SetDimensions(*reversed(labels.shape))
    image.SetSpacing(1, 1, 1)
    image.GetPointData().SetScalars(numpy_to_vtk(labels.ravel(order="C"), deep=True))
    meshes = []
    for label in label_codes:
        extract = vtkDiscreteFlyingEdges3D()
        extract.SetInputData(image)
        extract.SetValue(0, label)
        extract.ComputeNormalsOff()
        extract.Update()
        poly = extract.GetOutput()
        if not poly.GetNumberOfPoints() or not poly.GetNumberOfPolys():
            raise ValueError("Synthetic structure has no reconstructable surface.")
        points_ijk = vtk_to_numpy(poly.GetPoints().GetData()).astype(np.float64)
        cells = vtk_to_numpy(poly.GetPolys().GetData()).reshape(-1, 4)
        if not np.all(cells[:, 0] == 3) or len(cells) > 250000:
            raise ValueError("Synthetic surface exceeds the triangle profile.")
        triangles = cells[:, 1:].astype(np.int32)
        vertices = points_ijk @ volume.affine_lps[:3, :3].T + volume.affine_lps[:3, 3]
        cross = np.cross(vertices[triangles[:, 1]]-vertices[triangles[:, 0]],
                         vertices[triangles[:, 2]]-vertices[triangles[:, 0]])
        area = np.linalg.norm(cross, axis=1)/2
        keep = area > 1e-10
        triangles, area = triangles[keep], area[keep]
        if not len(triangles) or not np.isfinite(vertices).all():
            raise ValueError("Synthetic surface is empty or nonfinite.")
        voxel_count = int(np.count_nonzero(labels == label))
        payload = {
            "label": label, "vertices_lps_mm": np.round(vertices, 6).tolist(),
            "triangles": triangles.tolist(), "voxel_count": voxel_count,
            "voxel_volume_mm3": float(voxel_count * np.linalg.det(volume.affine_lps[:3, :3])),
            "surface_area_mm2": float(area.sum()), "degenerate_triangles_removed": int((~keep).sum()),
            "bounds_lps_mm": [vertices.min(axis=0).tolist(), vertices.max(axis=0).tolist()],
        }
        meshes.append({**payload, "surface_sha256": canonical_digest(payload)})
    return {
        "schema_version": "synthetic-knee-surfaces-v1", "algorithm": "vtkDiscreteFlyingEdges3D",
        "vtk_version": vtkVersion.GetVTKVersion(), "coordinate_system": "LPS_mm",
        "source_volume_sha256": volume.to_manifest()["volume_sha256"],
        "label_source": "analytic_synthetic_ground_truth",
        "label_sha256": hashlib.sha256(labels.tobytes(order="C")).hexdigest(),
        "color_source": "conventional_structure_palette", "smoothing_applied": False,
        "is_clinically_validated": False, "meshes": meshes,
    }
