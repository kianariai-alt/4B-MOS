"""Synthetic, database-free tests for the existing-registry read boundary."""

from dataclasses import FrozenInstanceError, replace, dataclass
from datetime import date, datetime, timezone
import json
from types import SimpleNamespace
import unittest

from backend.app.imaging_intelligence.knowledge import (
    IMAGING_KNOWLEDGE_DOMAINS, ImagingKnowledgeRegistryAdapter,
)


TODAY = date(2026, 10, 19)


@dataclass(frozen=True)
class SyntheticFact:
    id: str = "fact-1"
    fact_key: str = "IMAGING.TEST.1"
    version: int = 1
    content_sha256: str = "a" * 64
    status: str = "approved"
    clinical_domain: str = "imaging_knee_xray"
    valid_from: date | None = None
    valid_to: date | None = None
    created_by_user_id: str = "synthetic-author"
    reviewed_by_user_id: str | None = "synthetic-reviewer"
    reviewed_at: datetime | None = datetime(2026, 10, 1, tzinfo=timezone.utc)
    sources: tuple = (SimpleNamespace(id="source-1", title="unexported source content"),)
    statement: str = "Unexported synthetic medical text, not real clinical evidence."


class ImagingKnowledgeTests(unittest.TestCase):
    def references(self, *facts, domain="imaging_knee_xray", as_of=TODAY):
        def reader(db, *, skip, limit, **kwargs):
            return list(facts[skip:skip + limit])
        return ImagingKnowledgeRegistryAdapter(reader).collect(object(), domain=domain, as_of=as_of)

    def test_empty_reference_snapshot_for_each_domain_without_readiness_claim(self):
        for domain in IMAGING_KNOWLEDGE_DOMAINS:
            result = self.references(domain=domain).to_dict()
            self.assertEqual(result["clinical_domain"], domain)
            self.assertEqual(result["readiness"], "empty")
            self.assertFalse(result["is_diagnosis"])
            self.assertFalse(result["is_recommendation"])
            self.assertFalse(result["is_clinical_validation"])
            self.assertEqual(result["patient_applicability"], "not_assessed")

    def test_reference_export_is_minimized_immutable_and_json_compatible(self):
        fact = SyntheticFact()
        result = self.references(fact)
        reference = result.facts[0]
        self.assertEqual(reference.source_ids, ("source-1",))
        self.assertEqual(reference.content_sha256, fact.content_sha256)
        encoded = json.dumps(result.to_dict())
        for private_field in ("statement", "reviewed_by_user_id", "created_by_user_id", "title"):
            self.assertNotIn(private_field, encoded)
        with self.assertRaises(FrozenInstanceError):
            reference.version = 2
        # A caller can change its serialized copy without changing the snapshot.
        exported = result.to_dict()
        exported["facts"][0]["source_ids"].append("other")
        self.assertEqual(reference.source_ids, ("source-1",))

    def test_order_is_canonical_and_source_identity_changes_digest(self):
        first = SyntheticFact()
        second = replace(first, id="fact-2", fact_key="IMAGING.TEST.2")
        self.assertEqual(self.references(first, second), self.references(second, first))
        changed = replace(first, sources=(SimpleNamespace(id="source-2"),))
        self.assertNotEqual(self.references(first).references_sha256, self.references(changed).references_sha256)
        later = self.references(first, as_of=date(2026, 10, 20))
        self.assertNotEqual(self.references(first).references_sha256, later.references_sha256)

    def test_drafts_cross_domains_and_case_changes_fail_closed(self):
        for changes in ({"status": "draft"}, {"clinical_domain": "orthopedics_knee"},
                        {"clinical_domain": "IMAGING_KNEE_XRAY"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.references(replace(SyntheticFact(), **changes))
        with self.assertRaises(ValueError):
            self.references(domain="orthopedics_knee")

    def test_validity_window_is_inclusive_and_rejects_expired_future_or_malformed(self):
        self.references(replace(SyntheticFact(), valid_from=TODAY, valid_to=TODAY))
        for changes in ({"valid_from": date(2026, 10, 20)}, {"valid_to": date(2026, 10, 18)},
                        {"valid_from": "2026-10-19"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.references(replace(SyntheticFact(), **changes))

    def test_absent_or_self_attributed_approval_is_rejected(self):
        for changes in ({"reviewed_by_user_id": None}, {"reviewed_at": None},
                        {"reviewed_by_user_id": "synthetic-author"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.references(replace(SyntheticFact(), **changes))

    def test_reference_fields_and_source_uniqueness_are_validated_without_echoing_values(self):
        for changes in ({"version": True}, {"version": 0}, {"content_sha256": "untrusted secret"},
                        {"id": "patient/secret"}, {"sources": ()},
                        {"sources": (SimpleNamespace(id="source-1"), SimpleNamespace(id="source-1"))}):
            with self.subTest(changes=changes), self.assertRaises(ValueError) as caught:
                self.references(replace(SyntheticFact(), **changes))
            self.assertNotIn("secret", str(caught.exception))

    def test_duplicate_id_or_fact_key_version_is_rejected(self):
        fact = SyntheticFact()
        for duplicate in (fact, replace(fact, id="fact-2"), replace(fact, fact_key="OTHER.KEY")):
            with self.subTest(duplicate=duplicate), self.assertRaises(ValueError):
                self.references(fact, duplicate)

    def test_registry_adapter_uses_supplied_session_exact_domains_date_and_pagination(self):
        db = object()
        calls = []
        facts = [SyntheticFact(), replace(SyntheticFact(), id="fact-2", fact_key="SECOND.KEY")]

        def reader(actual_db, **kwargs):
            self.assertIs(actual_db, db)
            calls.append(kwargs)
            start = kwargs["skip"]
            return facts[start:start + kwargs["limit"]]

        result = ImagingKnowledgeRegistryAdapter(reader, page_size=1).collect(db, domain="imaging_knee_xray", as_of=TODAY)
        self.assertEqual(len(result.facts), 2)
        self.assertEqual([call["skip"] for call in calls], [0, 1, 2])
        self.assertTrue(all(call["as_of"] == TODAY and call["limit"] == 1 for call in calls))
        self.assertEqual([call["clinical_domain"] for call in calls],
                         ["imaging_knee_xray"] * 3)

    def test_registry_integrity_failure_propagates_without_reinterpreting_content(self):
        class SyntheticIntegrityError(Exception):
            pass

        def reader(*args, **kwargs):
            raise SyntheticIntegrityError("Synthetic integrity failure")

        with self.assertRaises(SyntheticIntegrityError):
            ImagingKnowledgeRegistryAdapter(reader).collect(object(), domain="imaging_knee_xray", as_of=TODAY)

    def test_registry_misbehaving_pages_are_rejected_and_collection_is_bounded(self):
        for response in (None, [SyntheticFact()] * 2,
                         [replace(SyntheticFact(), clinical_domain="imaging_knee_mri")]):
            with self.subTest(response=response), self.assertRaises(ValueError):
                ImagingKnowledgeRegistryAdapter(lambda *args, **kwargs: response, page_size=1).collect(
                    object(), domain="imaging_knee_xray", as_of=TODAY,
                )
        with self.assertRaisesRegex(ValueError, "limit"):
            ImagingKnowledgeRegistryAdapter(lambda *args, **kwargs: [SyntheticFact()], page_size=1).collect(
                object(), domain="imaging_knee_xray", as_of=TODAY,
            )

    def test_date_and_page_size_reject_implicit_or_unbounded_inputs(self):
        for page_size in (True, 0, 201):
            with self.subTest(page_size=page_size), self.assertRaises(ValueError):
                ImagingKnowledgeRegistryAdapter(page_size=page_size)
        with self.assertRaises(ValueError):
            self.references(as_of=datetime.now(timezone.utc))


if __name__ == "__main__":
    unittest.main()
