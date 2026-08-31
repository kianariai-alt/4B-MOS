from datetime import datetime
from typing import Literal

from pydantic import BaseModel


TimelineItemType = Literal[
    "visit",
    "treatment",
    "session",
    "audit",
]


class PatientTimelineItem(BaseModel):
    id: str
    timestamp: datetime

    item_type: TimelineItemType

    entity_type: str
    entity_id: str
    event_type: str

    title: str
    status: str | None = None

    actor_user_id: str | None = None
    actor_username: str | None = None
    actor_display_name: str | None = None
    actor_role: str | None = None

    details: dict | None = None


class PatientTimelineResponse(BaseModel):
    patient_id: str
    count: int
    items: list[PatientTimelineItem]