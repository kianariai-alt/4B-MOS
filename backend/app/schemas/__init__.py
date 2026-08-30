from backend.app.schemas.patient import (
    PatientCreate,
    PatientRead,
    PatientUpdate,
)

from backend.app.schemas.treatment import (
    TreatmentCreate,
    TreatmentRead,
    TreatmentUpdate,
)

from backend.app.schemas.visit import (
    VisitCreate,
    VisitRead,
    VisitUpdate,
)

__all__ = [
    "PatientCreate",
    "PatientRead",
    "PatientUpdate",
    "VisitCreate",
    "VisitRead",
    "VisitUpdate",
    "TreatmentCreate",
    "TreatmentRead",
    "TreatmentUpdate",
]