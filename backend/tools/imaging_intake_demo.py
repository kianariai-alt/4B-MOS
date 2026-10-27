"""Run the content-to-volume and technical validation path on generated data."""

import argparse
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import zipfile

from backend.imaging_desktop.received import receive
from backend.imaging_desktop.volume import load_series
from backend.tools.synthetic_knee_fixture import generate_knee_dicom


def run_demo():
    with TemporaryDirectory(prefix="4b-generated-intake-") as folder:
        fixture = generate_knee_dicom(Path(folder), size=32)
        bundle = BytesIO()
        with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
            for index, item in enumerate(fixture.source.instances):
                archive.writestr(f"slice-{index}.bin", item.path.read_bytes())
            archive.writestr("synthetic-report.pdf", b"%PDF-1.7\nSynthetic format-detection fixture only.")
        received = receive(bundle.getvalue())
    volume = load_series(received.catalog.series[0])
    return {"synthetic_only": True, "received": received.report(), "volume": volume.report(),
            "other_formats": [receive(raw).report() for raw in (
                b"%PDF-1.7\nSynthetic detection fixture.", b"\xff\xd8\xffsynthetic-signature-fixture",
                b"\x00\x00\x00\x20ftypisom", b"\xff\x00unknown-fixture",
            )]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    result = json.dumps(run_demo(), indent=2)+"\n"
    if arguments.output:
        arguments.output.write_text(result, encoding="utf-8")
    else:
        print(result, end="")
