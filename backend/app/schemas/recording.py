"""Recording metadata only: this phase never accepts audio or trains a model."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

class RecordingCommand(Strict):
    expected_version: int = Field(strict=True, ge=0)
    request_key: str = Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")

class RecordingStart(RecordingCommand):
    recording_id: str = Field(min_length=36, max_length=36, pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")
    expected_consent_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

class RecordingFinish(RecordingCommand):
    recording_id: str = Field(min_length=36, max_length=36, pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")
    reason: Literal["finished", "consent_changed", "connection_lost", "microphone_error", "app_closing", "duration_limit", "interrupted", "session_changed"]
    pcm_bytes: int = Field(strict=True, ge=0, le=460800000)
    encrypted_file_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

class RecordingEventRead(Strict):
    id: str
    visit_id: str
    recording_id: str
    version: int
    action: Literal["start", "finish"]
    recorded_by: str
    created_at: str
    request_key: str
    command: dict
    consent_event_id: str
    consent_sha256: str
    sha256: str

class RecordingAccess(Strict):
    visit_id: str
    patient_id: str
    patient_code: str
    physician_id: str
    version: int
    can_record: bool
    block_reason: Literal["consent_required", "visit_closed", "session_active"] | None
    consent_event_id: str | None
    consent_sha256: str | None
    active_recording: RecordingEventRead | None
    audio_upload_enabled: Literal[False] = False
    transcription_enabled: Literal[False] = False
    training_enabled: Literal[False] = False

class RecordingCheck(Strict):
    recording_id: str
    can_continue: bool
    reason: Literal["consent_changed", "visit_closed", "session_changed", "duration_limit"] | None
    version: int
