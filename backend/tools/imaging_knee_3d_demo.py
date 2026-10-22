"""Export an offline synthetic knee viewer from generated DICOM and label truth.

Accepts an output directory and a verified Three.js package directory; no patient
file, image-center URL, database or segmentation model can be supplied.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

import numpy as np
import pydicom

from backend.app.imaging_intelligence.models import canonical_digest
from backend.app.imaging_intelligence.reconstruction import SyntheticVolumeReconstructor
from backend.app.imaging_intelligence.surface_reconstruction import reconstruct_surfaces
from backend.tools.imaging_metadata_demo import SYNTHETIC_REFERENCE_KEY
from backend.tools.synthetic_knee_fixture import STRUCTURES, generate_knee_dicom
from backend.tools.knee_anatomy import EXTRA_STRUCTURES, TEMPLATE_ROOT, anatomy_provenance


# Immutable r180 source, commit 0af9729d0c143a86a1d725d6e2c3ad83301f3f34.
# Only these verified, locally copied runtime files are used; no CDN or scripts.
THREE_FILES = {
    "build/three.module.js": "c8211c69345d2e9949dc7a8ac969380497aa0600a5a8ac6a459c8cd02dd9cb8a",
    "build/three.core.js": "eb077d2417f61d3e6d9264c317cabc4ea35769ed6b0ab533067292a550784c20",
    "examples/jsm/controls/OrbitControls.js": "b97879c748170baadeb3fb84cea1ffdf4674e283dc06042f34e2acb95a76042c",
    "LICENSE": "bfe119ea4fd413f5f7ca3fcd63adb0c4a073ed39daa2fe7d3e6b769e21272601",
}


def verified_three_assets(root: Path):
    try:
        if json.loads((root / "package.json").read_text())["version"] != "0.180.0":
            raise ValueError()
        result = {}
        for path, expected in THREE_FILES.items():
            if (root/path).stat().st_size > 2*1024*1024:
                raise ValueError()
            content = (root/path).read_bytes()
            if hashlib.sha256(content).hexdigest() != expected:
                raise ValueError()
            result[Path(path).name] = content
        return result
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError("Verified Three.js 0.180.0 runtime assets are required.") from None


def export_synthetic_knee(output: Path, *, three_root: Path, modality="MR", size=96):
    assets = verified_three_assets(three_root)
    if output.exists():
        raise ValueError("Output directory must be new.")
    with TemporaryDirectory(prefix="4b-generated-knee-") as folder:
        fixture = generate_knee_dicom(Path(folder), modality=modality, size=size, anatomical=True)
        volume = SyntheticVolumeReconstructor(reference_key=SYNTHETIC_REFERENCE_KEY).reconstruct(fixture.source)
        if not np.array_equal(volume.voxels, fixture.expected_values):
            raise ValueError("Synthetic DICOM pixel round trip failed.")
        surfaces = reconstruct_surfaces(volume, fixture.labels, label_codes=tuple(range(1, 14)),
                                        display_smoothing=True)
        surfaces["label_source"] = "generic_bone_templates_and_procedural_synthetic_ground_truth"
        voxel_bytes = volume.voxels.tobytes(order="C")
        label_bytes = fixture.labels.tobytes(order="C")
    palette = [{"label": label, "code": code, "title": title, "color": color}
               for label, code, title, color in STRUCTURES + EXTRA_STRUCTURES]
    backend = Path(__file__).resolve().parents[1]
    source_paths = ("app/imaging_intelligence/reconstruction.py", "app/imaging_intelligence/surface_reconstruction.py",
                    "tools/synthetic_knee_fixture.py", "tools/knee_anatomy.py", "tools/imaging_knee_3d_demo.py",
                    "imaging_3d_viewer/app.js", "imaging_3d_viewer/index.html", "imaging_3d_viewer/style.css")
    scene = {
        "schema_version": "synthetic-knee-viewer-v2", "synthetic_only": True,
        "volume": volume.to_manifest(), "surfaces": surfaces, "structures": palette,
        "assets": {"volume.f32": hashlib.sha256(voxel_bytes).hexdigest(),
                   "labels.u8": hashlib.sha256(label_bytes).hexdigest()},
        "source": "generic_anatomical_phantom_not_patient_anatomy",
        "anatomy": anatomy_provenance(),
        "segmentation": "known_phantom_labels_not_an_inferred_segmentation",
        "synthetic_pixel_roundtrip_verified": True, "authorizes_treatment": False,
        "is_clinically_validated": False,
        "processing": {"pydicom_version": pydicom.__version__, "numpy_version": np.__version__,
                       "vtk_version": surfaces["vtk_version"], "three_version": "0.180.0",
                       "source_sha256s": {name:hashlib.sha256((backend/name).read_bytes()).hexdigest()
                                           for name in source_paths}, "three_runtime_sha256s": THREE_FILES},
        "limitations": ["generic_unvalidated_illustration", "procedural_soft_tissues", "illustrative_pose",
                        "display_smoothing_not_for_measurement", "conventional_colors", "no_arthroscopy_equivalence",
                        "no_automatic_segmentation", "no_physiological_motion", "no_patient_file_input"],
    }
    scene["artifact_sha256"] = canonical_digest(scene)
    output.mkdir(parents=True)
    (output/"vendor").mkdir()
    for name, content in assets.items():
        (output/"vendor"/name).write_bytes(content)
    viewer = Path(__file__).resolve().parents[1] / "imaging_3d_viewer"
    for name in ("index.html", "app.js", "style.css"):
        shutil.copyfile(viewer/name, output/name)
    (output/"scene.json").write_text(json.dumps(scene, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    (output/"volume.f32").write_bytes(voxel_bytes)
    (output/"labels.u8").write_bytes(label_bytes)
    shutil.copyfile(TEMPLATE_ROOT/"ATTRIBUTION.md", output/"ANATOMY_ATTRIBUTION.md")
    (output/"README.txt").write_text(
        "4B-MOS synthetic knee demonstration; no patient data or clinical validation.\n"
        "Generic template femur/tibia; illustrative soft tissues and pose; no patient segmentation.\n"
        "Display smoothing is separate from the original voxel-boundary measurement surfaces.\n"
        "Run inside this folder: python -m http.server 18765 --bind 127.0.0.1\n"
        "Open http://127.0.0.1:18765 in a WebGL2 browser. Direct file:// loading is unsupported.\n"
        "Use W/A/S/D and R/F only while the internal-view canvas is focused.\n"
        "OpenSim template credits and CC-BY-3.0 license: ANATOMY_ATTRIBUTION.md\n"
        "Third-party Three.js license: vendor/LICENSE\n")
    summary = {
        "schema_version": scene["schema_version"], "synthetic_only": True,
        "modality": modality, "shape_zyx": list(volume.voxels.shape),
        "structures": len(surfaces["meshes"]),
        "triangles": sum(len(mesh["triangles"]) for mesh in surfaces["meshes"]),
        "artifact_sha256": scene["artifact_sha256"], "volume_sha256": scene["volume"]["volume_sha256"],
        "label_source": surfaces["label_source"], "vtk_version": surfaces["vtk_version"],
        "anatomy_profile": scene["anatomy"]["profile"], "display_smoothing_only": True,
        "synthetic_pixel_roundtrip_verified": True, "is_clinically_validated": False,
    }
    (output/"verification.json").write_text(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2)+"\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--three-root", type=Path, required=True)
    parser.add_argument("--modality", choices=("MR", "CT"), default="MR")
    parser.add_argument("--size", choices=(64, 96), type=int, default=96)
    args = parser.parse_args()
    print(json.dumps(export_synthetic_knee(args.output, three_root=args.three_root,
                                          modality=args.modality, size=args.size), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
