"""Typed audio transfer and encrypted transcription/review boundaries."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class Strict(BaseModel):
    model_config=ConfigDict(extra="forbid",str_strip_whitespace=True)

class InitializeAudio(Strict):
    request_key: str=Field(min_length=8,max_length=100,pattern=r"^[A-Za-z0-9_.-]+$")
    pcm_bytes: int=Field(strict=True,gt=0,le=57600000)
    pcm_sha256: str=Field(pattern=r"^[a-f0-9]{64}$")
    encrypted_file_sha256: str=Field(pattern=r"^[a-f0-9]{64}$")
    sample_rate: Literal[16000]=16000
    channels: Literal[1]=1
    sample_bits: Literal[16]=16
    @model_validator(mode="after")
    def aligned(self):
        if self.pcm_bytes%2: raise ValueError("PCM must contain whole 16-bit samples.")
        return self

class CompleteAudio(Strict):
    request_key: str=Field(min_length=8,max_length=100,pattern=r"^[A-Za-z0-9_.-]+$")
    expected_pcm_sha256: str=Field(pattern=r"^[a-f0-9]{64}$")

class TextCommand(Strict):
    expected_version: int=Field(strict=True,ge=0)
    request_key: str=Field(min_length=8,max_length=100,pattern=r"^[A-Za-z0-9_.-]+$")

class ReviewText(TextCommand):
    expected_draft_sha256: str=Field(pattern=r"^[a-f0-9]{64}$")
    edited_text: str=Field(min_length=1,max_length=200000)
    statement_fa: str=Field(min_length=20,max_length=2000)

class TranscriptSegment(Strict):
    start: float=Field(ge=0,allow_inf_nan=False)
    end: float=Field(ge=0,allow_inf_nan=False)
    text: str=Field(min_length=1,max_length=4000)
    speaker: Literal["unknown"]="unknown"
    @model_validator(mode="after")
    def order(self):
        if self.end<self.start:raise ValueError("Segment end precedes start.")
        return self

class TranscriptContent(Strict):
    text: str=Field(min_length=1,max_length=200000)
    language: Literal["fa"]="fa"
    engine: Literal["faster-whisper"]="faster-whisper"
    model_id: str=Field(min_length=1,max_length=200)
    model_fingerprint: str=Field(pattern=r"^[a-f0-9]{64}$")
    segments: list[TranscriptSegment]=Field(min_length=1,max_length=5000)
    speaker_identification_verified: Literal[False]=False

class DraftRead(Strict):
    id: str
    sha256: str
    created_at: str
    content: TranscriptContent
    reviewed_by_physician: Literal[False]=False

class ReviewRead(Strict):
    id: str
    sha256: str
    created_at: str
    draft_sha256: str
    edited_text: str
    statement_fa: str
    recorded_by: str
    reviewed_by_physician: Literal[True]=True

class MediaStatus(Strict):
    recording_id: str
    transfer_id: str | None=None
    transfer_sha256: str | None=None
    chunk_bytes: int=262144
    next_chunk_index: int=0
    received_pcm_bytes: int=0
    expected_pcm_bytes: int=0
    audio_received: bool=False
    version: int=0
    state: Literal["not_uploaded","uploading","audio_received","queued","running","failed","draft","reviewed"]="not_uploaded"
    failure_code: str | None=None
    audio_upload_enabled: bool
    transcription_enabled: bool
    training_enabled: Literal[False]=False
    authorizes_diagnosis: Literal[False]=False

class MediaWorkspace(MediaStatus):
    latest_draft: DraftRead | None=None
    latest_review: ReviewRead | None=None
