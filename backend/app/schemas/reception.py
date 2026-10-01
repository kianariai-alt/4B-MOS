"""Administrative data only; no diagnosis or treatment authorization fields."""

from datetime import datetime, timezone
from typing import Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

ConsentPurpose = Literal[
    "care", "audio_recording", "educational_use", "follow_up_contact", "marketing"
]
CONSENT_PURPOSES = (
    "care",
    "audio_recording",
    "educational_use",
    "follow_up_contact",
    "marketing",
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ReceptionContent(StrictModel):
    patient_reported_complaint: str = Field(min_length=3, max_length=3000)
    care_goal: str | None = Field(default=None, max_length=2000)
    phone: str | None = Field(default=None, max_length=40)
    preferred_channel: Literal["phone", "sms", "none", "unknown"] = "unknown"
    preferred_contact_time: str | None = Field(default=None, max_length=100)
    assigned_physician_id: str | None = Field(default=None, min_length=1, max_length=36)
    state: Literal["draft", "ready_for_screen"] = "draft"

    @model_validator(mode="after")
    def ready_requires_physician(self):
        if self.state == "ready_for_screen" and not self.assigned_physician_id:
            raise ValueError("Assign a physician before marking ready for screening.")
        return self


class ReceptionCreate(ReceptionContent):
    expected_version: int = Field(ge=0, strict=True)
    request_key: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")


class ConsentCreate(StrictModel):
    purpose: ConsentPurpose
    state: Literal["granted", "declined", "withdrawn"]
    document_version: str = Field(min_length=1, max_length=100)
    evidence_reference: str = Field(min_length=8, max_length=500)
    confirmed_at: AwareDatetime
    expected_version: int = Field(ge=0, strict=True)
    request_key: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")

    @model_validator(mode="after")
    def confirmation_not_future(self):
        if self.confirmed_at > datetime.now(timezone.utc):
            raise ValueError("Consent confirmation cannot be in the future.")
        return self


class EvidenceRead(StrictModel):
    id: str
    visit_id: str
    version: int
    request_key: str
    recorded_by: str
    created_at: datetime
    sha256: str
    content: dict


class ConsentState(StrictModel):
    purpose: ConsentPurpose
    state: Literal["unknown", "granted", "declined", "withdrawn"]
    latest_event: EvidenceRead | None


class ReceptionWorkspace(StrictModel):
    visit_id: str
    patient_id: str
    latest_intake: EvidenceRead | None
    intake_version: int
    consent_version: int
    consents: list[ConsentState]
    authorizes_treatment: Literal[False] = False
