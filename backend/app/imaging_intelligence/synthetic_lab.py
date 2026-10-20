"""Fixed-loopback synthetic DICOMweb laboratory client, never a production connector."""

from email.parser import BytesParser
from email.policy import default
import io
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import pydicom

from backend.tools.imaging_metadata_demo import SYNTHETIC_REFERENCE_KEY
from backend.tools.imaging_series_demo import (
    SYNTHETIC_SERIES_UID, SYNTHETIC_STUDY_UID, generate_synthetic_series,
)

from .series import SeriesMetadataReader, StudySeriesValidator


LAB_ORIGIN = "http://127.0.0.1:18042"
LAB_NAME = "4B-MOS-SYNTHETIC-ONLY"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class SyntheticLabError(RuntimeError):
    pass


class SyntheticDicomWebLab:
    def __init__(self, *, transport=None):
        self._client = httpx.Client(base_url=LAB_ORIGIN, timeout=5, follow_redirects=False,
                                    trust_env=False, transport=transport)

    def close(self):
        self._client.close()

    def _request(self, method, path, **kwargs):
        try:
            with self._client.stream(method, path, **kwargs) as response:
                response.raise_for_status()
                chunks, length = [], 0
                for chunk in response.iter_bytes():
                    length += len(chunk)
                    if length > MAX_RESPONSE_BYTES:
                        raise ValueError()
                    chunks.append(chunk)
                return response.headers, b"".join(chunks)
        except Exception:
            raise SyntheticLabError("Synthetic imaging lab request failed.") from None

    def assert_synthetic_lab(self):
        try:
            _, data = self._request("GET", "/system")
            import json
            if json.loads(data).get("Name") != LAB_NAME:
                raise ValueError()
        except Exception:
            raise SyntheticLabError("Expected isolated synthetic Orthanc lab is unavailable.") from None

    def run(self):
        """Generate, upload, QIDO, WADO metadata and retrieve only a known synthetic fixture."""
        self.assert_synthetic_lab()
        try:
            import json
            with TemporaryDirectory(prefix="4b-lab-generated-") as folder:
                fixture = generate_synthetic_series(Path(folder))
                for path in fixture.files:
                    # No caller-provided file path or bytes can enter this upload.
                    boundary = "4b-synthetic-stow-v1"
                    body = (f"--{boundary}\r\nContent-Type: application/dicom\r\n\r\n".encode()
                            + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode())
                    self._request("POST", "/dicom-web/studies", content=body,
                                  headers={"Content-Type":f'multipart/related; type="application/dicom"; boundary={boundary}'})
                _, study_data = self._request("GET", "/dicom-web/studies", params={"StudyInstanceUID":SYNTHETIC_STUDY_UID},
                                              headers={"Accept":"application/dicom+json"})
                studies = json.loads(study_data)
                if len(studies) != 1 or studies[0]["0020000D"]["Value"] != [SYNTHETIC_STUDY_UID]:
                    raise ValueError()
                series_path = f"/dicom-web/studies/{SYNTHETIC_STUDY_UID}/series/{SYNTHETIC_SERIES_UID}"
                _, metadata_data = self._request("GET", series_path + "/metadata", headers={"Accept":"application/dicom+json"})
                metadata = json.loads(metadata_data)
                if len(metadata) != 3:
                    raise ValueError()
                retrieved = []
                for index, dataset in enumerate(metadata):
                    uid = dataset["00080018"]["Value"][0]
                    if uid not in {f"1.2.826.0.1.3680043.10.543.210{i}" for i in range(3)}:
                        raise ValueError()
                    headers, body = self._request("GET", series_path + "/instances/" + uid,
                                                  headers={"Accept":"multipart/related; type=application/dicom"})
                    message = BytesParser(policy=default).parsebytes(
                        b"Content-Type: " + headers["content-type"].encode("ascii") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body)
                    if not message.is_multipart() or len(message.get_payload()) != 1:
                        raise ValueError()
                    raw = message.get_payload(0).get_payload(decode=True)
                    parsed = pydicom.dcmread(io.BytesIO(raw), stop_before_pixels=True)
                    if str(parsed.SOPInstanceUID) != uid or parsed.PatientID != "SYNTHETIC-DEMO-ID-NEVER-EXPORT":
                        raise ValueError()
                    target = Path(folder) / f"retrieved-{index}.dcm"
                    target.write_bytes(raw)
                    retrieved.append(target)
                report = StudySeriesValidator(SeriesMetadataReader(reference_key=SYNTHETIC_REFERENCE_KEY)).read(
                    retrieved, expected=(fixture.expected,))
                if report.status != "valid":
                    raise ValueError()
                return {"synthetic_only":True, "qido_study_count":1, "wado_instance_count":len(retrieved),
                        "study":report.to_dict(), "is_diagnosis":False, "dicom_identity_verified":False}
        except Exception:
            raise SyntheticLabError("Synthetic DICOMweb round trip failed.") from None
