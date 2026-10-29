"""Metadata-only central recording inbox for the current recording physician."""
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator

from backend.app.schemas.capture_origin import CaptureOrigin


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RecordingInboxQuery(Strict):
    room_code: StrictStr | None = Field(default=None, min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    limit: StrictInt = Field(default=50, ge=1, le=100)
    offset: StrictInt = Field(default=0, ge=0)


class RecordingInboxItem(Strict):
    visit_id: str
    recording_id: str
    captured_at: AwareDatetime
    finished_at: AwareDatetime
    capture_origin: CaptureOrigin | None
    origin_missing_for_legacy: StrictBool
    capture_state: Literal["finished"] = "finished"
    media_state: Literal["not_uploaded", "uploading", "audio_received", "queued", "running", "failed", "draft", "reviewed"]
    audio_received: StrictBool

    @model_validator(mode="after")
    def origin_consistency(self):
        if self.origin_missing_for_legacy != (self.capture_origin is None):
            raise ValueError("Legacy origin absence must be explicit; no room identity is inferred.")
        return self


class RecordingInboxRead(Strict):
    items: tuple[RecordingInboxItem, ...] = Field(max_length=100)
    next_offset: StrictInt | None = Field(default=None, ge=0)
    audio_upload_enabled: StrictBool
    transcription_enabled: StrictBool
    origin_is_authenticated_hardware: Literal[False] = False
    contains_transcript_text: Literal[False] = False
    training_enabled: Literal[False] = False

    @field_validator("origin_is_authenticated_hardware", "contains_transcript_text", "training_enabled", mode="before")
    @classmethod
    def exact_false(cls, value):
        if type(value) is not bool or value is not False:
            raise ValueError("Inbox metadata cannot authenticate hardware, contain transcript text or train a model.")
        return value
