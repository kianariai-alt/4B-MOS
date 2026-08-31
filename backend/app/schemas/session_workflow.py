from typing import Literal

from pydantic import BaseModel


SessionOperationalStatus = Literal[
    "scheduled",
    "checked_in",
    "ready",
    "in_treatment",
    "completed",
    "discharged",
    "cancelled",
]


class SessionWorkflowUpdate(BaseModel):
    operational_status: (
        SessionOperationalStatus
    )