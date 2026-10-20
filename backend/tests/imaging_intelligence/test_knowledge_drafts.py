import copy
import json
import unittest

from backend.app.imaging_intelligence.knowledge_drafts import prepare_registry_drafts
from backend.tools.imaging_knowledge_drafts import PACK_PATH, draft_plan


class KnowledgeDraftTests(unittest.TestCase):
    def setUp(self):
        self.pack = json.loads(PACK_PATH.read_text())

    def test_real_registry_schema_accepts_all_six_drafts_without_approval(self):
        result = draft_plan()
        self.assertTrue(result["dry_run"])
        self.assertFalse(result["database_accessed"])
        self.assertEqual(result["approved_fact_count"], 0)
        self.assertEqual(len(result["drafts"]), 6)
        self.assertTrue(all(x["status"] == "draft" for x in result["drafts"]))
        self.assertEqual({x["payload"]["clinical_domain"] for x in result["drafts"]},
                         {"imaging_knee_xray", "imaging_knee_mri"})

    def test_approval_or_review_injection_fails_closed(self):
        for key, value in (("status", "approved"), ("reviewed_by_user_id", "synthetic-reviewer")):
            pack = copy.deepcopy(self.pack)
            pack["candidates"][0]["payload"][key] = value
            with self.assertRaises(ValueError):
                prepare_registry_drafts(pack)
        self.pack["status"] = "approved"
        with self.assertRaises(ValueError):
            prepare_registry_drafts(self.pack)

    def test_cross_domain_duplicate_source_and_missing_limitations_are_rejected(self):
        for change in ("domain", "duplicate", "source", "limitations"):
            pack = copy.deepcopy(self.pack)
            if change == "domain":
                pack["candidates"][0]["payload"]["clinical_domain"] = "orthopedics_knee"
            elif change == "duplicate":
                pack["candidates"].append(pack["candidates"][0])
            elif change == "source":
                pack["candidates"][0]["payload"]["sources"][0]["url"] = "https://token:password@example.com/data"
            else:
                pack["candidates"][0]["limitations"] = []
            with self.subTest(change=change), self.assertRaises(ValueError):
                prepare_registry_drafts(pack)

    def test_reordering_is_stable_and_semantic_change_updates_digest(self):
        first = prepare_registry_drafts(self.pack)
        self.pack["candidates"].reverse()
        self.assertEqual(first, prepare_registry_drafts(self.pack))
        self.pack["candidates"][0]["payload"]["statement"] += " Independent review pending."
        self.assertNotEqual(first, prepare_registry_drafts(self.pack))

    def test_unavailable_acr_fulltext_stays_in_review_queue(self):
        self.assertEqual(self.pack["source_review_queue"][0]["status"], "needs_full_text_and_version_review")
        for draft in prepare_registry_drafts(self.pack):
            self.assertNotIn("acsearch.acr.org", draft.payload_json)


if __name__ == '__main__':
    unittest.main()
