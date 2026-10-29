"""Minimum reported workstation context; not authenticated hardware identity.

These identifiers distinguish capture locations and client sessions. They must
not contain patient names, email addresses, microphone recordings or secrets.
"""
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictStr


CaptureIdentifier = Annotated[
    StrictStr,
    Field(pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$"),
]


class CaptureOrigin(BaseModel):
    """Client-reported source labels, never permission to access a visit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    room_code: StrictStr = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    device_id: CaptureIdentifier
    client_session_id: CaptureIdentifier
