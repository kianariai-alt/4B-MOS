from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditLogRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
    )

    id: str
    entity_type: str
    entity_id: str
    event_type: str

    from_state: str | None
    to_state: str | None

    message: str | None
    event_data: dict | None

    created_at: datetime