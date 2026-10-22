"""Generic educational knee phantom; template bones and constructed soft tissues.

This does not infer anatomy from an image. See knee_templates/ATTRIBUTION.md.
Coordinates are a left-knee illustration: +x lateral, -y anterior, +z superior.
"""

import hashlib
from pathlib import Path

import numpy as np


TEMPLATE_ROOT = Path(__file__).with_name("knee_templates")
TEMPLATE_SHA256S = {
    "femur_r.vtp": "7afa9aca4c4640f25b5c7ff78eee60c193ca035b0c026a54bf693eb698a41aff",
    "tibia_r.vtp": "079a4758e876a49f4969e354c5a9924cddbddf7bc641744fce9b5be7c9254171",
}
EXTENT_XYZ_MM = (120., 110., 220.)
EXTRA_STRUCTURES = (
    (9, "fibula", "استخوان نازک‌نی", "#e8ddc6"),
    (10, "mcl", "رباط جانبی داخلی", "#e5cdb6"),
    (11, "lcl", "رباط جانبی خارجی", "#ddc3a8"),
    (12, "patellar_tendon", "تاندون کشکک", "#f0e3d1"),
    (13, "quadriceps_tendon", "تاندون چهارسر", "#eee1cb"),
)


def anatomy_provenance():
    return {
        "profile": "generic-left-knee-illustration-v2",
        "bone_template_repository": "https://github.com/opensim-org/opensim-models",
        "bone_template_commit": "d9b05d470b1a481c222372c85b75772faf8f7792",
        "bone_template_sha256s": dict(TEMPLATE_SHA256S),
        "license": "CC-BY-3.0", "attribution_file": "ANATOMY_ATTRIBUTION.md",
        "modifications": ["right_to_left_mirroring", "metres_to_millimetres",
                          "illustrative_translation_and_shaft_crop", "voxelization"],
        "soft_tissues": "procedural_illustrations_not_atlas_segmentations",
        "pose": "illustrative_clearance_not_an_opensim_simulation",
        "anatomical_accuracy_validated": False,
    }


def _bone_mask(name, size, spacing, z_translation):
    from vtkmodules.vtkIOXML import vtkXMLPolyDataReader
    from vtkmodules.vtkCommonCore import vtkPoints
    from vtkmodules.vtkImagingStencil import vtkPolyDataToImageStencil
    from vtkmodules.util.numpy_support import numpy_to_vtk, vtk_to_numpy

    raw = (TEMPLATE_ROOT / name).read_bytes()
    if hashlib.sha256(raw).hexdigest() != TEMPLATE_SHA256S[name]:
        raise ValueError("Anatomical template integrity check failed.")
    reader = vtkXMLPolyDataReader()
    reader.ReadFromInputStringOn()
    reader.SetInputString(raw.decode("utf-8"))
    reader.Update()
    poly = reader.GetOutput()
    original = vtk_to_numpy(poly.GetPoints().GetData()).astype(float) * 1000
    # OpenSim right-bone axes: anterior X, superior Y, lateral Z.
    points = np.column_stack((original[:, 2], -original[:, 0], original[:, 1] + z_translation))
    vtk_points = vtkPoints()
    vtk_points.SetData(numpy_to_vtk(points, deep=True))
    poly.SetPoints(vtk_points)
    stencil = vtkPolyDataToImageStencil()
    stencil.SetInputData(poly)
    stencil.SetOutputOrigin(*(-np.asarray(EXTENT_XYZ_MM) / 2))
    stencil.SetOutputSpacing(*spacing)
    stencil.SetOutputWholeExtent(0, size-1, 0, size-1, 0, size-1)
    stencil.Update()
    result = np.zeros((size, size, size), dtype=bool)
    # Read actual stencil runs; this also avoids an extra image allocation.
    from vtkmodules.vtkCommonCore import reference
    out = stencil.GetOutput()
    for k in range(size):
        for j in range(size):
            start, end, cursor = reference(0), reference(0), reference(0)
            while out.GetNextExtent(start, end, 0, size-1, j, k, cursor):
                result[k, j, int(start):int(end)+1] = True
    return result


def anatomical_knee(size=96, modality="MR"):
    """Known labels for 13 illustrated structures on a fixed physical domain."""
    if type(size) is not int or size not in {64, 96} or modality not in {"MR", "CT"}:
        raise ValueError("The anatomical phantom requires size 64 or 96 and MR/CT.")
    spacing = np.asarray(EXTENT_XYZ_MM) / (size - 1)
    z, y, x = np.meshgrid(*(np.linspace(-extent/2, extent/2, size)
                           for extent in reversed(EXTENT_XYZ_MM)), indexing="ij")
    labels = np.zeros(x.shape, dtype=np.uint8)
    femur = _bone_mask("femur_r.vtp", size, spacing, 432.)
    tibia = _bone_mask("tibia_r.vtp", size, spacing, 25.)
    # Rounded caps at the illustration's cropped shaft ends, away from the joint.
    femur &= z < 99 - .012*(x*x + y*y)
    tibia &= z > -99 + .012*(x*x + y*y)
    labels[femur] = 1
    labels[tibia] = 2

    def ellipsoid(cx, cy, cz, rx, ry, rz):
        return ((x-cx)/rx)**2 + ((y-cy)/ry)**2 + ((z-cz)/rz)**2 < 1

    def tube(points, radius_x, radius_y=None):
        # Piecewise curved ribbons, in physical mm; not anatomical fibre inference.
        radius_y = radius_y or radius_x
        output = np.zeros(x.shape, dtype=bool)
        for a, b in zip(np.asarray(points[:-1]), np.asarray(points[1:])):
            d = b-a
            t = np.clip(((x-a[0])*d[0] + (y-a[1])*d[1] + (z-a[2])*d[2])/(d@d), 0, 1)
            output |= ((x-a[0]-t*d[0])/radius_x)**2 + ((y-a[1]-t*d[1])/radius_y)**2 + ((z-a[2]-t*d[2])/radius_x)**2 < 1
        return output

    # Patella: broad superior base, narrow inferior apex, posterior articular ridge.
    v = (z-28)/23
    width = np.interp(v, [-1, -.5, .3, 1], [3, 15, 21, 15])
    patella = (np.abs(v) < 1) & ((x/width)**2 + ((y+39)/8)**2 < (1-v*v))
    labels[patella] = 3
    fibula = tube([(42, 6, -29), (44, 7, -42), (42, 8, -65), (39, 9, -97)], 4.5)
    fibula |= ellipsoid(42, 6, -29, 7, 8, 10)
    labels[fibula & (labels == 0)] = 9

    # Cartilage follows the actual voxelized bone surface, only on joint faces.
    # A local dilation is implemented with shifts; no optional SciPy dependency.
    def shell(mask):
        expanded = mask.copy()
        for axis in range(3):
            expanded |= np.roll(mask, 1, axis) | np.roll(mask, -1, axis)
        return expanded & ~mask

    tibial_top = np.where(tibia, z, -np.inf).max(axis=0)
    tibial_roof = tibial_top[None, :, :]
    cartilage = ((shell(femur) & (z < 26) & (z > -3)) |
                 (shell(tibia) & (z > tibial_roof) & (tibial_roof > -18) & (y < 24)) |
                 (shell(patella) & (y > -37)))
    labels[cartilage & (labels == 0)] = 4
    # C-shaped wedges: open toward the intercondylar region, thicker at the rim.
    for label, cx, rx, ry, gap in ((5, -16, 15, 23, .60), (6, 20, 16, 21, .42)):
        u, v = (x-cx)/rx, (y-1)/ry
        radius = np.sqrt(u*u + v*v)
        inward = -np.sign(cx)*u
        rim = np.clip((radius-.48)/.55, 0, 1)
        bottom = tibial_top[None, :, :] + spacing[2]*.8
        meniscus = ((radius > .48) & (radius < 1.03) & (inward < gap) & (tibial_roof > -18) &
                    (z > bottom) & (z < bottom + 2.8 + 4.7*rim))
        labels[meniscus & (labels == 0)] = label
    # Distinct anterior/posterior tibial origins and crossing femoral insertions.
    soft = (
        (7, tube([(-6, -12, -8), (0, -2, 6), (12, 9, 25)], 3.4)),
        (8, tube([(7, 16, -9), (3, 8, 7), (-11, -3, 26)], 4.2)),
        (10, tube([(-35, -1, 29), (-39, -2, 9), (-37, -3, -15), (-28, -5, -45)], 3.4, 8)),
        (11, tube([(34, 4, 28), (41, 6, 2), (42, 6, -27)], 3.2)),
        (12, tube([(0, -39, 7), (0, -39, -10), (0, -32, -34)], 10, 3.2)),
        (13, tube([(0, -38, 45), (0, -32, 65), (0, -28, 94)], 12, 3.8)),
    )
    for label, mask in soft:
        labels[mask & (labels == 0)] = label
    # Ensure the whole volume is padded for closed surface extraction.
    for face in (labels[0], labels[-1], labels[:, 0], labels[:, -1], labels[:, :, 0], labels[:, :, -1]):
        face[:] = 0
    body = (x/55)**2 + ((y+2)/49)**2 < 1
    values = np.where(body, 90 if modality == "MR" else 45, 0 if modality == "MR" else -1000).astype(np.int16)
    levels = ((0, 430, 410, 420, 870, 170, 180, 120, 135, 410, 130, 135, 145, 150)
              if modality == "MR" else (0, 950, 900, 930, 65, 55, 58, 60, 62, 900, 60, 60, 65, 65))
    for label in range(1, 14):
        values[labels == label] = levels[label]
    values += np.arange(size, dtype=np.int16)[:, None, None] % 7
    labels.setflags(write=False)
    values.setflags(write=False)
    return labels, values
