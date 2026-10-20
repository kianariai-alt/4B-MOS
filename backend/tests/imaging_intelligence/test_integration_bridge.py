from dataclasses import replace
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from backend.app.decision_intelligence import ClinicalInput
from backend.app.imaging_intelligence.integration import GatedImagingRecordAdapter, ReportSeriesBinding
from backend.app.imaging_intelligence.series import SeriesMetadataReader, StudySeriesValidator
from backend.tools.imaging_metadata_demo import SYNTHETIC_REFERENCE_KEY
from backend.tools.imaging_series_demo import generate_synthetic_series


def actual_contract():
    path = os.environ.get("MOS_INTEGRATION_CONTRACT_FILE")
    if path:
        spec = importlib.util.spec_from_file_location("mos_pinned_integration_contract", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    try:
        from backend.app.schemas import clinical_integration
        return clinical_integration
    except ImportError:
        return None


CONTRACT = actual_contract()


@unittest.skipIf(CONTRACT is None, "Pinned PR44 contract is provided by compatibility CI or an installed integration core.")
class IntegrationBridgeTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        fixture = generate_synthetic_series(Path(folder.name))
        validator = StudySeriesValidator(SeriesMetadataReader(reference_key=SYNTHETIC_REFERENCE_KEY))
        self.study = validator.read(fixture.files, expected=(fixture.expected,))
        self.binding = ReportSeriesBinding("synthetic-report", 1, "b"*64, "c"*64, self.study.series[0].sha256)
        self.clinical = ClinicalInput(("assessment_context", "clinical_review"), "KNEE", "L")
        self.source = CONTRACT.RecordReference(record_type="paraclinical_report", record_id="synthetic-report",
                                               version=1, content_sha256="b"*64, observation_id="synthetic-observation", field="observation")
        self.context = CONTRACT.CoreInput(visit_id="synthetic-visit", clinical_context_sha256="c"*64,
            observations=(CONTRACT.SourceObservation(source=self.source, observation={
                "category":"imaging", "code_system":"LOCAL", "code":"SYNTHETIC_ONLY",
                "display_name":"Synthetic recorded observation", "value_type":"boolean", "boolean_value":True,
            }),))

    def adapter(self, **overrides):
        args = dict(study=self.study, binding=self.binding, clinical=self.clinical, contract=CONTRACT,
                    clock=lambda:datetime(2026,10,20,tzinfo=timezone.utc))
        args.update(overrides)
        return GatedImagingRecordAdapter(**args)

    def test_actual_v1_schema_accepts_output_and_preserves_record(self):
        adapter = self.adapter()
        result = adapter.collect(self.context)
        CONTRACT.CoreOutput.model_validate_json(result.model_dump_json())
        self.assertEqual(result.status, "available")
        self.assertEqual(adapter.validation().status, "data_ready")
        self.assertEqual(result.findings[0].source, self.source)
        self.assertEqual(result.findings[0].observation, self.context.observations[0].observation)
        self.assertEqual(result.findings[0].origin, "record")
        self.assertIsNone(result.findings[0].confidence)
        self.assertEqual(result.component, adapter.current_version())

    def test_output_has_no_dicom_fields_review_claims_or_uid(self):
        result = self.adapter().collect(self.context).model_dump(mode="json")
        self.assertEqual(set(result), {"contract_version","core","visit_id","clinical_context_sha256",
                                     "component","generated_at","valid_until","status","findings"})
        payload = json.dumps(result)
        for text in ("dicom_identity_verified", "review_status", "1.2.826.0.1.3680043", "SYNTHETIC^DEMO_ONLY"):
            self.assertNotIn(text, payload)

    def test_invalid_study_or_unestablished_completeness_never_passes(self):
        for study in (replace(self.study, status="invalid"),
                      replace(self.study, series=(replace(self.study.series[0], completeness="not_established"),))):
            result = self.adapter(study=study).collect(self.context)
            self.assertEqual(result.status,"unavailable")
            self.assertEqual(result.findings,())

    def test_stale_context_report_version_hash_or_binding_blocks_output(self):
        for changes in ({"clinical_context_sha256":"d"*64}, {"report_version":2},
                        {"report_content_sha256":"d"*64}, {"series_sha256":"d"*64}):
            result = self.adapter(binding=replace(self.binding, **changes)).collect(self.context)
            self.assertEqual(result.status,"unavailable")

    def test_missing_clinical_fields_and_laterality_mismatch_block(self):
        for clinical in (ClinicalInput(), replace(self.clinical,laterality="R")):
            self.assertEqual(self.adapter(clinical=clinical).collect(self.context).status,"unavailable")

    def test_no_record_means_missing_and_metadata_does_not_manufacture_findings(self):
        context = self.context.model_copy(update={"observations":()})
        result = self.adapter().collect(context)
        self.assertEqual(result.status,"missing")
        self.assertEqual(result.findings,())

    def test_unbound_record_cannot_be_silently_mixed_into_result(self):
        extra = self.context.observations[0].model_copy(update={"source":self.source.model_copy(update={"record_id":"other-report"})})
        context = self.context.model_copy(update={"observations":self.context.observations+(extra,)})
        self.assertEqual(self.adapter().collect(context).status,"unavailable")

    def test_naive_clock_and_unsupported_contract_rejected(self):
        with self.assertRaises(ValueError):
            self.adapter(clock=lambda:datetime(2026,10,20)).collect(self.context)
        with self.assertRaises(ValueError):
            self.adapter(contract=type("OtherContract",(),{"CONTRACT_VERSION":"2.0.0"}))


if __name__ == '__main__':
    unittest.main()
