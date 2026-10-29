"""Human-reviewed, deidentified interview-learning handoff contracts.

Attestations record a clinician's review; they are not automated guarantees of
deidentification, speaker identity, medical accuracy or model training.
"""
from __future__ import annotations

import hashlib
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator, model_validator

from backend.app.schemas.capture_origin import CaptureIdentifier, CaptureOrigin
from backend.app.schemas.physician_questions import BankContent, BankEventRead


Digest = Annotated[StrictStr, Field(pattern=r"^[a-f0-9]{64}$")]
RequestKey = Annotated[StrictStr, Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)


class LearningQuestionAnnotation(Strict):
    start: StrictInt = Field(ge=0)
    end: StrictInt = Field(gt=0)
    text_fa: StrictStr = Field(min_length=3, max_length=1000)
    stage: Literal["reception", "initial_visit", "physician_visit"]
    speaker: Literal["clinician"] = "clinician"

    @model_validator(mode="after")
    def span_order(self):
        if self.end <= self.start or not self.text_fa.strip():
            raise ValueError("A question requires a nonempty, forward source-text span.")
        return self


class VisitLearningPacket(Strict):
    schema_version: Literal["1.0.0"] = "1.0.0"
    packet_id: CaptureIdentifier
    capture_origin: CaptureOrigin
    recording_id: CaptureIdentifier
    source_type: Literal["local_transcript", "server_reviewed_transcript"]
    source_review_sha256: Digest | None = None
    source_text_sha256: Digest
    deidentified_reviewed_text: StrictStr = Field(min_length=1, max_length=100000)
    question_annotations: tuple[LearningQuestionAnnotation, ...] = Field(default=(), max_length=100)
    deidentification_reviewed: Literal[True]
    speaker_attribution_reviewed: Literal[True]
    expected_audio_consent_sha256: Digest
    expected_educational_consent_sha256: Digest
    summary_preferences_fa: StrictStr | None = Field(default=None, max_length=2000)

    @field_validator("deidentification_reviewed", "speaker_attribution_reviewed", mode="before")
    @classmethod
    def explicit_human_attestation(cls, value):
        if type(value) is not bool or value is not True:
            raise ValueError("Explicit human deidentification and speaker review are required.")
        return value

    @model_validator(mode="after")
    def bind_reviewed_text_and_questions(self):
        text = self.deidentified_reviewed_text
        if not text.strip() or hashlib.sha256(text.encode("utf-8")).hexdigest() != self.source_text_sha256:
            raise ValueError("The source-text hash must match the exact reviewed UTF-8 text.")
        if (self.source_type == "server_reviewed_transcript") != (self.source_review_sha256 is not None):
            raise ValueError("Only server-reviewed transcripts require a server review hash.")
        previous_end = 0
        for item in self.question_annotations:
            if item.start < previous_end or item.end > len(text) or text[item.start:item.end] != item.text_fa:
                raise ValueError("Question annotations must be ordered, nonoverlapping exact source-text spans.")
            previous_end = item.end
        return self


class VisitLearningSubmit(Strict):
    packet: VisitLearningPacket
    request_key: RequestKey
    expected_version: StrictInt = Field(default=0, ge=0, le=0)


class VisitLearningReviewCommand(Strict):
    expected_version: StrictInt = Field(ge=1)
    expected_packet_sha256: Digest
    request_key: RequestKey
    statement_fa: StrictStr = Field(min_length=20, max_length=2000)


class VisitLearningPromote(VisitLearningReviewCommand):
    expected_bank_version: StrictInt = Field(ge=0)
    title_fa: StrictStr = Field(default="پیش‌نویس پرسش‌های ویزیت برای بازبینی پزشک", min_length=3, max_length=200)


class VisitLearningSummary(Strict):
    packet_id: str
    visit_id: str
    recording_id: str
    physician_id: str
    capture_origin: CaptureOrigin
    source_type: Literal["local_transcript", "server_reviewed_transcript"]
    version: int
    status: Literal["submitted", "bank_draft", "rejected"]
    packet_sha256: Digest
    event_sha256: Digest
    question_count: int
    created_at: str
    bank_event_id: str | None = None
    capture_origin_is_client_reported: Literal[True] = True
    model_training_performed: Literal[False] = False
    medical_knowledge_changed: Literal[False] = False
    safety_rules_changed: Literal[False] = False


class VisitLearningRead(Strict):
    summary: VisitLearningSummary
    packet: VisitLearningPacket
    automated_deidentification_guaranteed: Literal[False] = False
    automatic_speaker_identification_verified: Literal[False] = False
    model_training_performed: Literal[False] = False


class VisitLearningBankPreview(Strict):
    summary: VisitLearningSummary
    bank: BankContent | None
    review_requirements_fa: tuple[str, ...]
    branches_inferred: Literal[False] = False
    activation_performed: Literal[False] = False
    model_training_performed: Literal[False] = False


class VisitLearningPromotion(Strict):
    summary: VisitLearningSummary
    bank_event: BankEventRead
    activation_performed: Literal[False] = False
    model_training_performed: Literal[False] = False
