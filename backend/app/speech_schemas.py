"""Additive voice contracts. All times use the source's media clock, in ms."""

from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from app.schemas import ProcessedTurn, Speaker, StrictModel


class TimedWord(StrictModel):
    text: str = Field(min_length=1, max_length=200)
    start_ms: int = Field(ge=0, strict=True)
    end_ms: int = Field(ge=0, strict=True)
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def valid_word(self) -> Self:
        if not self.text.strip() or self.end_ms < self.start_ms:
            raise ValueError("Invalid timed word")
        return self


class TranscriptSegment(StrictModel):
    source_id: str = Field(min_length=1, max_length=128)
    segment_id: str = Field(min_length=1, max_length=128)
    revision: int = Field(default=0, ge=0, strict=True)
    is_final: bool = False
    speaker: Speaker | None = None
    review_required: bool = True
    text: str = Field(min_length=1, max_length=2000)
    start_ms: int = Field(ge=0, strict=True)
    end_ms: int = Field(ge=0, strict=True)
    words: list[TimedWord] = Field(default_factory=list, max_length=500)

    @field_validator("source_id", "segment_id", "text")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Value must not be blank")
        # Retain verbatim ASR wording, including fillers and whitespace.
        return value

    @model_validator(mode="after")
    def valid_timeline(self) -> Self:
        if self.end_ms <= self.start_ms:
            raise ValueError("Segment end must follow its start")
        previous_start = self.start_ms
        text_offset = 0
        for word in self.words:
            token = word.text.strip()
            position = self.text.find(token, text_offset)
            if (word.start_ms < previous_start or word.start_ms < self.start_ms
                    or word.end_ms > self.end_ms or position < 0):
                raise ValueError("Words must follow transcript order and stay within segment bounds")
            previous_start = word.start_ms
            text_offset = position + len(token)
        return self


class WordGap(StrictModel):
    source_id: str
    start_ms: int
    end_ms: int
    duration_ms: int
    basis: Literal["word_timestamps"] = "word_timestamps"


class TranscriptRecord(StrictModel):
    segment: TranscriptSegment
    gaps: list[WordGap] = Field(default_factory=list)
    turn: ProcessedTurn | None = None
    reviewed_text: str | None = None


class TranscriptReview(StrictModel):
    source_id: str = Field(min_length=1, max_length=128)
    segment_id: str = Field(min_length=1, max_length=128)
    speaker: Speaker
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Reviewed text must not be blank")
        return value


class TranscriptHistory(StrictModel):
    session_id: str
    segments: list[TranscriptRecord]
    audio_pauses: list["AudioPause"] = Field(default_factory=list)


class AudioPause(StrictModel):
    source_id: str
    start_ms: int
    end_ms: int
    duration_ms: int
    rms_threshold: float
    basis: Literal["pcm_rms"] = "pcm_rms"


class AudioStart(StrictModel):
    type: Literal["start"]
    source_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    speaker: Speaker | None = None
    sample_rate: Literal[16000] = 16000
    # Coaching is opt-in until audio quality and speaker routing are checked.
    enable_coaching: bool = False
    consent_confirmed: Literal[True]
