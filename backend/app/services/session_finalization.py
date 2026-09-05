"""Versioned evidence captured by the locked completion command only."""
from copy import deepcopy
import hashlib
import json

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.models.orthobiologic_material import OrthobiologicMaterial
from backend.app.models.session_finalization import SessionFinalization
from backend.app.models.treatment import Treatment
from backend.app.models.treatment_component import TreatmentComponent
from backend.app.models.treatment_session_component import TreatmentSessionComponent
from backend.app.repositories.treatment_component import TreatmentComponentRepository
from backend.app.repositories.treatment_session_component import TreatmentSessionComponentRepository
from backend.app.schemas.orthobiologic_material import OrthobiologicMaterialRead
from backend.app.schemas.session_finalization import SessionFinalizationRead
from backend.app.schemas.treatment import TreatmentRead
from backend.app.schemas.treatment_component import TreatmentComponentRead
from backend.app.schemas.treatment_session import TreatmentSessionRead
from backend.app.schemas.treatment_session_component import TreatmentSessionComponentRead
from backend.app.services.audit_context import actor_data


class FinalizationNotFoundError(Exception):
    pass


class FinalizationIntegrityError(Exception):
    pass


def evidence_digest(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class SessionFinalizationService:
    @staticmethod
    def lock_materials(db: Session, session) -> list[OrthobiologicMaterial]:
        # Parent treatment is already locked. Lock catalog rows in stable order
        # so the guard and evidence see the same lot-tracking policy. SQLite's
        # existing write lock supplies this protection there.
        planned = select(TreatmentComponent.material_id).where(TreatmentComponent.treatment_id == session.treatment_id)
        actual = select(TreatmentSessionComponent.material_id).where(TreatmentSessionComponent.treatment_session_id == session.id)
        return list(db.scalars(
            select(OrthobiologicMaterial)
            .where(or_(OrthobiologicMaterial.id.in_(planned), OrthobiologicMaterial.id.in_(actual)))
            .order_by(OrthobiologicMaterial.id).with_for_update()
            .execution_options(populate_existing=True)
        ))

    @staticmethod
    def capture(db: Session, session, completion_check, materials, actor, captured_at) -> SessionFinalization:
        """Flush only; caller owns lock, state validation, audits and commit."""
        if session.status != "completed" or not completion_check.can_complete:
            raise ValueError("Evidence requires a successful completion transition.")
        if db.get(SessionFinalization, session.id) is not None:
            raise FinalizationIntegrityError("Finalization evidence already exists.")
        treatment = db.get(Treatment, session.treatment_id)
        plans = TreatmentComponentRepository.list_by_treatment(db, session.treatment_id)
        actuals = TreatmentSessionComponentRepository.list_by_session(db, session.id)
        payload = {
            "schema_version": 1,
            "completion_policy_version": "completion-guard-v1",
            "captured_at": captured_at.isoformat(),
            "actor": actor_data(actor),
            "session": TreatmentSessionRead.model_validate(session).model_dump(mode="json"),
            "treatment": TreatmentRead.model_validate(treatment).model_dump(mode="json"),
            "planned_components": [TreatmentComponentRead.model_validate(row).model_dump(mode="json") for row in plans],
            "administrations": [TreatmentSessionComponentRead.model_validate(row).model_dump(mode="json") for row in actuals],
            "materials": [OrthobiologicMaterialRead.model_validate(row).model_dump(mode="json") for row in materials],
            # This is explicitly the decision BEFORE the status transition,
            # not a claim that warnings were acknowledged or digitally signed.
            "completion_check_before_transition": completion_check.model_dump(mode="json"),
        }
        payload = deepcopy(payload)
        record = SessionFinalization(
            session_id=session.id, captured_at=captured_at,
            payload=payload, sha256=evidence_digest(payload),
        )
        db.add(record)
        db.flush()
        return record

    @staticmethod
    def get(db: Session, session_id: str) -> SessionFinalizationRead:
        record = db.get(SessionFinalization, session_id)
        if record is None:
            raise FinalizationNotFoundError(
                "No captured finalization evidence exists for this session; "
                "historical evidence is not reconstructed from current records."
            )
        payload = record.payload
        valid = (
            isinstance(payload, dict)
            and payload.get("schema_version") == 1
            and isinstance(payload.get("session"), dict)
            and payload["session"].get("id") == session_id
        )
        try:
            valid = valid and evidence_digest(payload) == record.sha256
        except (TypeError, ValueError):
            valid = False
        if not valid:
            raise FinalizationIntegrityError("Stored finalization evidence failed its integrity check.")
        return SessionFinalizationRead(session_id=session_id, sha256=record.sha256, payload=deepcopy(record.payload))
