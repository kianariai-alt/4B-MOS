"""Exercise actual PR44 engine code in a separate checkout, with synthetic records only."""

import argparse
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from backend.app.decision_intelligence import ClinicalInput
from backend.app.imaging_intelligence.integration import (
    GatedImagingRecordAdapter, INTEGRATION_REFERENCE_COMMIT, ReportSeriesBinding,
)
from backend.app.imaging_intelligence.series import SeriesMetadataReader, StudySeriesValidator
from backend.tools.imaging_metadata_demo import SYNTHETIC_REFERENCE_KEY
from backend.tools.imaging_series_demo import generate_synthetic_series


def synthetic_gate(contract):
    now = datetime(2026,10,20,tzinfo=timezone.utc)
    with TemporaryDirectory(prefix="4b-integration-generated-") as folder:
        fixture = generate_synthetic_series(Path(folder))
        study = StudySeriesValidator(SeriesMetadataReader(reference_key=SYNTHETIC_REFERENCE_KEY)).read(
            fixture.files,expected=(fixture.expected,))
    imaging = contract.SourceObservation(
        source=contract.RecordReference(record_type="paraclinical_report",record_id="synthetic-report",
            version=1,content_sha256="b"*64,observation_id="synthetic-imaging-observation",field="observation"),
        observation={"category":"imaging","code_system":"LOCAL","code":"SYNTHETIC_ONLY",
                     "display_name":"Synthetic recorded observation","value_type":"boolean","boolean_value":True},
    )
    clinical = contract.SourceObservation(
        source=contract.RecordReference(record_type="clinical_intake",record_id="synthetic-intake",
            version=1,content_sha256="a"*64,field="pain_score"),
        observation={"category":"clinical_test","code_system":"LOCAL","code":"SYNTHETIC_PAIN",
                     "display_name":"Synthetic recorded score","value_type":"integer","integer_value":0},
    )
    context = contract.CoreInput(visit_id="synthetic-visit",clinical_context_sha256="c"*64,
                                observations=(clinical,imaging))
    adapter = GatedImagingRecordAdapter(
        study=study, binding=ReportSeriesBinding("synthetic-report",1,"b"*64,"c"*64,study.series[0].sha256),
        clinical=ClinicalInput(("assessment_context","clinical_review"),"KNEE","L"),
        contract=contract,clock=lambda:now,
    )
    return context,adapter,now


def run_actual_engine(reference_root: Path):
    reference_root = reference_root.resolve()
    head = subprocess.check_output(["git","-C",str(reference_root),"rev-parse","HEAD"],text=True).strip()
    if head != INTEGRATION_REFERENCE_COMMIT:
        raise ValueError("Integration reference checkout does not match the reviewed commit.")
    # Resolve only the separately owned integration modules from the pinned tree.
    # No files are copied into this branch and no migration/service command runs.
    import backend.app.schemas
    import backend.app.services
    backend.app.schemas.__path__.insert(0,str(reference_root/"backend/app/schemas"))
    backend.app.services.__path__.insert(0,str(reference_root/"backend/app/services"))
    contract = importlib.import_module("backend.app.schemas.clinical_integration")
    engine = importlib.import_module("backend.app.services.clinical_integration.engine")
    upstream_adapters = importlib.import_module("backend.app.services.clinical_integration.adapters")
    context,adapter,now = synthetic_gate(contract)
    # The upstream clock is intentionally not overridden. Use a current engine
    # evaluation time while the gate itself remains reproducible in local tests.
    now = datetime.now(timezone.utc)
    adapter.clock = lambda:now
    cores,issues = engine.collect_cores(context,{
        "orthopedic":upstream_adapters.FinalRecordAdapter("orthopedic"),"imaging":adapter,
    },now=now)
    common = dict(
        patient_id="synthetic-patient",visit=contract.VisitReference(visit_id="synthetic-visit",status="open"),
        context=context, assessment=contract.ClinicalAssessmentReference(
            intake_id="synthetic-intake",version=1,content_sha256="a"*64,body_region="KNEE",laterality="left"),
        studies=(contract.ImagingStudyReference(report_id="synthetic-report",version=1,content_sha256="b"*64),),
        cores=cores,knowledge=(),copilot_sha256="d"*64,safety_rule_set_sha256="e"*64,issues=issues,now=now,
    )
    unreviewed = engine.assemble_result(**common,approvals={})
    approvals = {engine.digest_model(item.source):contract.PhysicianApproval(
        physician_user_id="synthetic-physician",reviewed_at=now) for item in context.observations}
    reviewed = engine.assemble_result(**common,approvals=approvals)
    assert adapter.validation().status == "data_ready"
    assert unreviewed.workflow_state == "blocked" and not unreviewed.confirmed_findings
    assert reviewed.workflow_state == "awaiting_physician_review" and len(reviewed.confirmed_findings) == 2
    assert not reviewed.authorizes_treatment and not reviewed.is_clinical_clearance
    assert all(not x.dicom_identity_verified and x.modality == "unknown" for x in reviewed.imaging_studies)
    return {"synthetic_only":True,"reference_commit":head,"database_accessed":False,
            "validation":adapter.validation().to_dict(),
            "without_source_review":unreviewed.model_dump(mode="json"),
            "with_synthetic_source_review":reviewed.model_dump(mode="json")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-root",type=Path,required=True)
    args = parser.parse_args()
    print(json.dumps(run_actual_engine(args.reference_root),sort_keys=True,indent=2))
