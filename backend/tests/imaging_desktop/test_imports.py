from dataclasses import replace
from email.message import Message
from io import BytesIO
import json
import os
from pathlib import Path
import ssl
import subprocess
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request
import zipfile

import numpy as np
import pydicom

from backend.imaging_desktop import sources
from backend.imaging_desktop.sources import ImportFailure, SourceFiles, download, open_local, unpack, validate_https_url
from backend.imaging_desktop.volume import load_series, scan
from backend.tools.synthetic_knee_fixture import generate_knee_dicom


def archive_files(contents, names=None):
    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for i, content in enumerate(contents):
            archive.writestr(names[i] if names else f"series/slice-{i:03}.dcm", content)
    return output.getvalue()


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.fixture = generate_knee_dicom(self.path, size=32)

    def raw(self):
        return tuple(item.path.read_bytes() for item in self.fixture.source.instances)

    def edit(self, index=0, **values):
        path = self.fixture.source.instances[index].path
        ds = pydicom.dcmread(path)
        for key, value in values.items():
            if value is None:
                delattr(ds, key)
            else:
                setattr(ds, key, value)
        if "SOPInstanceUID" in values:
            ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
        ds.save_as(path, enforce_file_format=True)


class SourceTests(Fixture):
    def test_zip_and_local_folder_use_real_part10_bytes(self):
        zipped = unpack(archive_files((*self.raw(), b"not an image")))
        self.assertEqual(zipped.files, self.raw())
        self.assertEqual(zipped.ignored_files, 1)
        local = open_local(self.path)
        self.assertEqual(local.files, self.raw())
        self.assertEqual(unpack(self.raw()[0]).files, self.raw()[:1])

    def test_local_zip_can_exceed_individual_file_limit_but_remains_bounded(self):
        path = self.path/"download.zip"
        path.write_bytes(archive_files(self.raw()))
        self.assertEqual(open_local(path).files, self.raw())

    def test_traversal_absolute_symlink_and_encrypted_archives_are_rejected(self):
        for name in ("../patient.dcm", "/patient.dcm", "C:/patient.dcm", "..\\patient.dcm"):
            with self.subTest(name=name), self.assertRaisesRegex(ImportFailure, "unsafe_archive_entry"):
                unpack(archive_files([self.raw()[0]], [name]))
        output = BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            item = zipfile.ZipInfo("link.dcm")
            item.create_system = 3
            item.external_attr = 0o120777 << 16
            archive.writestr(item, self.raw()[0])
        with self.assertRaisesRegex(ImportFailure, "unsafe_archive_entry"):
            unpack(output.getvalue())

    def test_corrupt_zip_html_and_size_limits(self):
        for raw in (b"PK\x03\x04broken", b"<html>patient name secret</html>", b"broken DICOM"):
            with self.assertRaises(ImportFailure) as caught:
                unpack(raw)
            self.assertNotIn("patient name", str(caught.exception))
        with patch.object(sources, "MAX_FILE_BYTES", 100), self.assertRaises(ImportFailure):
            unpack(archive_files([self.raw()[0]]))
        with patch.object(sources, "MAX_FILES", 1), self.assertRaises(ImportFailure):
            unpack(archive_files(self.raw()))

    @unittest.skipIf(os.name == "nt", "Unprivileged Windows cannot create arbitrary symlinks.")
    def test_local_symlink_and_fifo_are_rejected_without_waiting(self):
        link = self.path/"link.dcm"
        link.symlink_to(self.fixture.source.instances[0].path)
        fifo = self.path/"fifo"
        os.mkfifo(fifo)
        for path in (link, fifo):
            with self.subTest(kind=path.name), self.assertRaises(ImportFailure):
                open_local(path)

    def test_cancel_prevents_unpack_and_local_processing(self):
        cancel = threading.Event()
        cancel.set()
        for operation in (lambda: unpack(archive_files(self.raw()), cancel=cancel), lambda: open_local(self.path, cancel=cancel)):
            with self.assertRaisesRegex(ImportFailure, "^cancelled$"):
                operation()

    def test_https_url_validation_and_same_origin_redirect_policy(self):
        self.assertEqual(validate_https_url("https://hospital.example:8443/download?token=secret"), ("hospital.example", 8443))
        self.assertEqual(validate_https_url("https://hospital.example:5010/Patient?studyKey=synthetic-only"), ("hospital.example", 5010))
        for url in ("http://hospital.example/data", "file:///tmp/data", "javascript:alert(1)",
                    "https://patient:secret@hospital.example/data", "https://hospital.example/data#secret",
                    "https://hospital.example/\nsecret", "https://hospital.example:99999/data"):
            with self.assertRaises(ImportFailure) as error:
                validate_https_url(url)
            self.assertNotIn("secret", str(error.exception))
        redirect = sources._SameOriginRedirect()
        request = Request("https://hospital.example/data", headers={"Authorization": "Bearer secret"})
        self.assertIsNotNone(redirect.redirect_request(request, None, 302, "", {}, "https://hospital.example/next"))
        for destination in ("https://other.example/data", "https://hospital.example:8443/data", "http://hospital.example/data"):
            with self.assertRaises(ImportFailure):
                redirect.redirect_request(request, None, 302, "", {}, destination)

    def test_bounded_stream_handles_no_length_truncation_html_and_cancellation(self):
        class Response(BytesIO):
            status = 200
            def __init__(self, raw, **headers):
                super().__init__(raw)
                self.headers = Message()
                for name, value in headers.items():
                    self.headers[name] = value
        self.assertEqual(sources._download_stream(Response(b"1234")), b"1234")
        for response in (Response(b"1234", **{"Content-Length": "5"}), Response(b"1234", **{"Content-Type": "text/html"}),
                         Response(b"1234", **{"Content-Encoding": "gzip"}), Response(b"1234", **{"Content-Length": "invalid"})):
            with self.assertRaises(ImportFailure):
                sources._download_stream(response)
        with patch.object(sources, "MAX_INPUT_BYTES", 3), self.assertRaisesRegex(ImportFailure, "download_size_limit"):
            sources._download_stream(Response(b"1234"))


class VolumeTests(Fixture):
    def test_no_synthetic_marker_required_and_voxels_exact_after_sorting(self):
        for i in range(32):
            self.edit(i, PatientID="NOT_A_FIXTURE_MARKER", PatientName="PRIVATE^NEVER_EXPORT")
        catalog = scan(SourceFiles(tuple(reversed(self.raw()))))
        loaded = load_series(catalog.series[0])
        np.testing.assert_array_equal(loaded.voxels, self.fixture.expected_values)
        self.assertFalse(loaded.voxels.flags.writeable or loaded.affine_lps.flags.writeable)
        self.assertEqual(loaded.completeness, "not_established")
        report = json.dumps(loaded.report())
        for text in ("PRIVATE", "NOT_A_FIXTURE", "1.2.826.0.1.3680043", str(self.path)):
            self.assertNotIn(text, report)
        self.assertFalse(loaded.report()["segmentation_performed"])

    def test_ct_signed_rescale_and_oblique_anisotropic_affine(self):
        a = 2**-.5
        fixture = generate_knee_dicom(self.path, size=32, modality="CT", spacing_xyz=(.7, 1.1, 1.8), orientation=(a,a,0,-a,a,0))
        self.fixture = fixture
        self.edit(0, RescaleSlope=2, RescaleIntercept=-100)
        loaded = load_series(scan(SourceFiles(self.raw())).series[0])
        np.testing.assert_array_equal(loaded.voxels[0], fixture.expected_values[0]*2-100)
        np.testing.assert_array_equal(loaded.voxels[1:], fixture.expected_values[1:])
        np.testing.assert_allclose(loaded.affine_lps, fixture.source.affine_lps, atol=1e-10)

    def test_multiple_series_are_selectable_without_combining_studies(self):
        original = self.raw()
        for i in range(32):
            self.edit(i, StudyInstanceUID="2.25.101", SeriesInstanceUID="2.25.102", SOPInstanceUID=f"2.25.{200+i}")
        catalog = scan(SourceFiles(original+self.raw()))
        self.assertEqual(len(catalog.series), 2)
        self.assertNotEqual(catalog.series[0].reference, catalog.series[1].reference)
        for series in catalog.series:
            self.assertEqual(load_series(series).voxels.shape, (32, 32, 32))

    def test_duplicates_missing_frame_gaps_and_shear_are_blocked(self):
        raw = self.raw()
        with self.assertRaisesRegex(ImportFailure, "duplicate_dicom_instance"):
            scan(SourceFiles(raw+raw[:1]))
        for values in ({"FrameOfReferenceUID": None}, {"ImagePositionPatient": [0,0,999]},
                       {"ImageOrientationPatient": [1,0,0,0,0,1]}):
            self.fixture = generate_knee_dicom(self.path, size=32)
            self.edit(0, **values)
            series = scan(SourceFiles(self.raw())).series[0]
            with self.assertRaisesRegex(ImportFailure, "inconsistent_or_nonrectilinear_series"):
                load_series(series)

    def test_truncated_pixels_and_invalid_rescale_never_return_a_partial_volume(self):
        for value in ({"PixelData": b"\x00\x00"}, {"RescaleSlope": 0}):
            self.fixture = generate_knee_dicom(self.path, size=32)
            self.edit(0, **value)
            with self.assertRaises(ImportFailure):
                load_series(scan(SourceFiles(self.raw())).series[0])

    def test_unsupported_frame_and_monochrome1_behavior(self):
        self.edit(0, NumberOfFrames=2)
        with self.assertRaisesRegex(ImportFailure, "classic_monochrome_mr_ct_required"):
            scan(SourceFiles(self.raw()))
        self.fixture = generate_knee_dicom(self.path, size=32)
        for i in range(32):
            self.edit(i, PhotometricInterpretation="MONOCHROME1")
        loaded = load_series(scan(SourceFiles(self.raw())).series[0])
        self.assertTrue(loaded.monochrome1)
        np.testing.assert_array_equal(loaded.voxels, self.fixture.expected_values)

    def test_voxel_limit_is_checked_before_decode_and_references_are_scoped(self):
        first, second = scan(SourceFiles(self.raw())), scan(SourceFiles(self.raw()))
        self.assertNotEqual(first.series[0].reference, second.series[0].reference)
        with patch("backend.imaging_desktop.volume.MAX_VOXELS", 100), self.assertRaisesRegex(ImportFailure, "voxel_limit"):
            load_series(first.series[0])
        cancel = threading.Event()
        cancel.set()
        with self.assertRaisesRegex(ImportFailure, "cancelled"):
            load_series(first.series[0], cancel=cancel)


@unittest.skipUnless(os.environ.get("MOS_DESKTOP_NETWORK_TEST") == "1", "Actual loopback TLS tests run in dedicated CI.")
class HttpsTests(Fixture):
    def setUp(self):
        super().setUp()
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        cert, key = self.path/"tls.crt", self.path/"tls.key"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-sha256", "-nodes", "-days", "1",
                        "-keyout", str(key), "-out", str(cert), "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost"],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        payload = archive_files(self.raw())
        self.requests = []
        requests = self.requests
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                requests.append(self.path)
                if self.path == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", "/data")
                    self.end_headers()
                    return
                if self.path == "/cross":
                    self.send_response(302)
                    self.send_header("Location", f"https://127.0.0.1:{self.server.server_port}/data")
                    self.end_headers()
                    return
                if self.headers.get("Authorization") != "Bearer fixture-only":
                    self.send_response(401)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.base = f"https://localhost:{server.server_port}"
        create = ssl.create_default_context
        self.trusted_context = create(cafile=str(cert))

    def test_real_verified_tls_download_auth_and_dicom_pixel_roundtrip(self):
        with patch.object(sources.ssl, "create_default_context", return_value=self.trusted_context):
            received = download(self.base+"/redirect", bearer_token="fixture-only")
        loaded = load_series(scan(received).series[0])
        np.testing.assert_array_equal(loaded.voxels, self.fixture.expected_values)
        self.assertEqual(self.requests, ["/redirect", "/data"])

    def test_real_auth_failure_and_cross_origin_redirect_do_not_leak_tokens(self):
        with patch.object(sources.ssl, "create_default_context", return_value=self.trusted_context):
            with self.assertRaisesRegex(ImportFailure, "authentication_required"):
                download(self.base+"/data")
            with self.assertRaisesRegex(ImportFailure, "cross_host_redirect_blocked"):
                download(self.base+"/cross", bearer_token="fixture-only")
        self.assertEqual(self.requests, ["/data", "/cross"])

    def test_untrusted_tls_certificate_is_rejected(self):
        with self.assertRaisesRegex(ImportFailure, "https_connection_failed"):
            download(self.base+"/data", bearer_token="fixture-only")
        self.assertEqual(self.requests, [])


if __name__ == "__main__":
    unittest.main()
