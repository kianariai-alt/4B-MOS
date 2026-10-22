"""VTK surfaces from explicit synthetic ground-truth labels; no image segmentation."""

import hashlib

import numpy as np

from .models import canonical_digest
from .reconstruction import ReconstructedVolume


def reconstruct_surfaces(volume: ReconstructedVolume, labels: np.ndarray, *, label_codes: tuple[int, ...],
                         display_smoothing: bool = False):
    """Half-voxel label boundaries, transformed into the source LPS frame.

    Measurements always use the original voxel boundary. Optional display-only
    smoothing has separate vertices and provenance; it cannot change the source
    voxels, masks, reference geometry, areas or volumes.
    """
    if (type(display_smoothing) is not bool or type(volume) is not ReconstructedVolume or not isinstance(labels, np.ndarray)
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
        mesh = {**payload, "surface_sha256": canonical_digest(payload)}
        if display_smoothing:
            from vtkmodules.vtkCommonCore import vtkPoints
            from vtkmodules.vtkCommonDataModel import vtkPolyData
            from vtkmodules.vtkFiltersCore import vtkWindowedSincPolyDataFilter
            display_poly = vtkPolyData()
            display_poly.DeepCopy(poly)
            physical_points = vtkPoints()
            physical_points.SetData(numpy_to_vtk(vertices, deep=True))
            display_poly.SetPoints(physical_points)
            smooth = vtkWindowedSincPolyDataFilter()
            smooth.SetInputData(display_poly)
            smooth.SetNumberOfIterations(15)
            smooth.SetPassBand(.1)
            smooth.BoundarySmoothingOff()
            smooth.FeatureEdgeSmoothingOff()
            smooth.NormalizeCoordinatesOn()
            smooth.Update()
            display_vertices = vtk_to_numpy(smooth.GetOutput().GetPoints().GetData()).astype(float)
            if display_vertices.shape != vertices.shape or not np.isfinite(display_vertices).all():
                raise ValueError("Invalid display-only smoothing output.")
            displacement = float(np.linalg.norm(display_vertices - vertices, axis=1).max())
            if displacement > 2*np.linalg.norm(volume.affine_lps[:3, :3], axis=0).max():
                raise ValueError("Display smoothing exceeded the fixture displacement bound.")
            display = {"vertices_lps_mm": np.round(display_vertices, 6).tolist(),
                       "algorithm": "vtkWindowedSincPolyDataFilter", "iterations": 15, "pass_band": .1,
                       "max_displacement_mm": displacement, "for_measurements": False,
                       "topology": "same_triangle_indices_as_reference_surface"}
            mesh["display"] = {**display, "sha256": canonical_digest(display)}
        meshes.append(mesh)
    return {
        "schema_version": "synthetic-knee-surfaces-v1", "algorithm": "vtkDiscreteFlyingEdges3D",
        "vtk_version": vtkVersion.GetVTKVersion(), "coordinate_system": "LPS_mm",
        "source_volume_sha256": volume.to_manifest()["volume_sha256"],
        "label_source": "analytic_synthetic_ground_truth",
        "label_sha256": hashlib.sha256(labels.tobytes(order="C")).hexdigest(),
        "color_source": "conventional_structure_palette", "smoothing_applied": False,
        "display_smoothing_applied": display_smoothing,
        "is_clinically_validated": False, "meshes": meshes,
    }
