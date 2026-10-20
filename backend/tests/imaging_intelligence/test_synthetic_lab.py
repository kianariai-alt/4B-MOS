from pathlib import Path
import json
import unittest

import httpx

from backend.app.imaging_intelligence.synthetic_lab import (
    LAB_NAME, MAX_RESPONSE_BYTES, SyntheticDicomWebLab, SyntheticLabError,
)


class SyntheticLabTests(unittest.TestCase):
    def test_lab_identity_checked_before_any_upload(self):
        requests = []
        def handle(request):
            requests.append(request)
            return httpx.Response(200,json={"Name":"another-server"})
        lab = SyntheticDicomWebLab(transport=httpx.MockTransport(handle))
        self.addCleanup(lab.close)
        with self.assertRaises(SyntheticLabError):
            lab.run()
        self.assertEqual(len(requests),1)
        self.assertEqual(requests[0].method,"GET")
        self.assertEqual(str(requests[0].url),"http://127.0.0.1:18042/system")

    def test_redirect_credentials_errors_and_large_payload_are_sanitized(self):
        for response in (httpx.Response(302,headers={"Location":"https://example.com/private"}),
                         httpx.Response(500,text="secret patient data"),
                         httpx.Response(200,content=b"x"*(MAX_RESPONSE_BYTES+1))):
            lab = SyntheticDicomWebLab(transport=httpx.MockTransport(lambda request:response))
            try:
                with self.assertRaisesRegex(SyntheticLabError,"Expected isolated synthetic") as result:
                    lab.assert_synthetic_lab()
                self.assertNotIn("secret",str(result.exception))
            finally:
                lab.close()

    def test_successful_lab_identity_has_no_external_lookup(self):
        def handle(request):
            self.assertEqual(request.url.host,"127.0.0.1")
            return httpx.Response(200,json={"Name":LAB_NAME})
        lab = SyntheticDicomWebLab(transport=httpx.MockTransport(handle))
        self.addCleanup(lab.close)
        lab.assert_synthetic_lab()

    def test_configuration_has_only_loopback_ports_and_no_remote_peers(self):
        root = Path(__file__).resolve().parents[3] / "deploy/imaging-lab"
        config = json.loads((root/"orthanc.json").read_text())
        self.assertFalse(config["DicomServerEnabled"])
        self.assertEqual(config["DicomWeb"]["Servers"],{})
        compose = (root/"compose.yaml").read_text()
        self.assertIn('127.0.0.1:18042:8042',compose)
        self.assertIn('127.0.0.1:18080:80',compose)
        self.assertIn('internal: true',compose)
        self.assertNotIn(':latest',compose)
        self.assertIn('dicomUploadEnabled: false',(root/"ohif-config.js").read_text())


if __name__ == '__main__':
    unittest.main()
