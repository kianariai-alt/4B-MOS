"""Limits for approved offline benchmark inputs and text-free review metrics."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from backend.app.services.speech_evaluation import MAX_TEXT_CHARACTERS, tokens

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

class ComparisonRead(Strict):
    normalization_version: str
    reference_sha256: str
    candidate_sha256: str
    reference_words: int
    candidate_words: int
    word_edit_distance: int
    word_edit_rate: float | None
    reference_characters: int
    candidate_characters: int
    character_edit_distance: int
    character_edit_rate: float | None
    numeric_sequence_changed: bool
    numeric_tokens_missing: int
    numeric_tokens_added: int
    protected_phrases_checked: int
    protected_phrase_count_changes: int
    requires_source_audio_review: bool
    clinical_accuracy_established: Literal[False] = False
    authorizes_diagnosis: Literal[False] = False
    training_performed: Literal[False] = False

class RevisionMetricsRead(Strict):
    recording_id: str
    draft_sha256: str
    review_sha256: str
    comparison_kind: Literal['physician_revision_distance'] = 'physician_revision_distance'
    comparison: ComparisonRead
    reference_verified_against_audio: Literal[False] = False

class BenchmarkCase(Strict):
    case_id: str = Field(min_length=1, max_length=80, pattern=r'^[A-Za-z0-9_.-]+$')
    category: Literal['orthography', 'numbers', 'negation', 'terms', 'noise', 'general']
    reference_verified: Literal[True]
    reference: str = Field(min_length=1, max_length=MAX_TEXT_CHARACTERS)
    candidate: str = Field(max_length=MAX_TEXT_CHARACTERS)
    protected_phrases: list[str] = Field(default_factory=list, max_length=30)
    @model_validator(mode='after')
    def bounded_phrases(self):
        if any(not p.strip() or len(p) > 200 for p in self.protected_phrases):
            raise ValueError('Protected phrases must contain 1 to 200 characters.')
        if not tokens(self.reference):
            raise ValueError('Reference must contain normalized text tokens.')
        tokens(self.candidate)
        return self

class BenchmarkDataset(Strict):
    dataset_id: str = Field(min_length=1, max_length=80, pattern=r'^[A-Za-z0-9_.-]+$')
    dataset_kind: Literal['synthetic', 'approved_deidentified']
    authorized_for_evaluation: Literal[True]
    cases: list[BenchmarkCase] = Field(min_length=1, max_length=200)
    @model_validator(mode='after')
    def unique_cases(self):
        if len({c.case_id for c in self.cases}) != len(self.cases):
            raise ValueError('Benchmark case identifiers must be unique.')
        return self
