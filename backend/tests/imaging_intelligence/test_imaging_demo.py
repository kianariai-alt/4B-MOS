import json
import unittest

from backend.tools.imaging_metadata_demo import run_synthetic_demo


class ImagingDemoTests(unittest.TestCase):
    def test_local_synthetic_pipeline_and_unverified_finding_gate(self):
        result = run_synthetic_demo()
        self.assertEqual(result, run_synthetic_demo())
        self.assertTrue(result["synthetic_only"])
        self.assertFalse(result["database_accessed"])
        scenarios = result["scenarios"]
        self.assertEqual(scenarios["complete"]["metadata"]["status"], "valid")
        self.assertEqual(scenarios["complete"]["validation"]["status"], "data_ready")
        self.assertEqual(scenarios["incomplete"]["metadata"]["status"], "incomplete")
        self.assertEqual(scenarios["incomplete"]["validation"]["status"], "needs_data")
        self.assertEqual(scenarios["corrupt"]["metadata"]["status"], "invalid")
        self.assertEqual(scenarios["corrupt"]["validation"]["status"], "needs_data")
        blocked = scenarios["unverified_finding"]["validation"]
        self.assertEqual(blocked["status"], "needs_data")
        self.assertEqual(blocked["eligible_finding_references"], ())
        self.assertEqual(len(blocked["blocked_finding_references"]), 1)
        payload = json.dumps(result)
        for secret in ("SYNTHETIC^DEMO_ONLY", "SYNTHETIC-DEMO-ID", "1.2.826.0.1.3680043.10.543.1001", "/tmp/"):
            self.assertNotIn(secret, payload)


if __name__ == "__main__":
    unittest.main()
