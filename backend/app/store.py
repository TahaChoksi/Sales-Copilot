"""In-memory session store. Sessions disappear when the server restarts.

This is intentionally not a production datastore and has no user authentication.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4

from app.coaching import recommend
from app.detection import detect
from app.speech import word_gaps
from app.speech_schemas import AudioPause, TranscriptHistory, TranscriptRecord, TranscriptReview, TranscriptSegment
from app.schemas import (
    AnalysisResult, BuyingSignal, ConversationState, CreateSession, ProcessedTurn,
    ProductContext, SessionView, Speaker, TurnInput,
)


class MissingSession(Exception):
    pass


class ClosedSession(Exception):
    pass


class TranscriptConflict(Exception):
    pass


@dataclass
class _Session:
    session_id: str
    created_at: datetime
    product: ProductContext
    ended_at: datetime | None = None
    turns: list[ProcessedTurn] = field(default_factory=list)
    transcripts: dict[tuple[str, str], TranscriptRecord] = field(default_factory=dict)
    source_positions: dict[str, tuple[int, int | None]] = field(default_factory=dict)
    audio_sources: set[str] = field(default_factory=set)
    audio_pauses: list[AudioPause] = field(default_factory=list)

    def snapshot(self) -> SessionView:
        # Minimal in-memory conversation state derived from confirmed turns.
        # "observed" is deliberate: the app cannot yet tell whether objections
        # have been resolved, and must not claim they are unresolved.
        state = ConversationState()
        for turn in self.turns:
            if turn.speaker == Speaker.CUSTOMER:
                state.last_customer_message = turn.text
                state.last_customer_signal = turn.analysis.buying_signal
                for objection in turn.analysis.objections:
                    if objection not in state.observed_objections:
                        state.observed_objections.append(objection)
            else:
                state.last_salesperson_message = turn.text
        # Callers own snapshots; nested models must not alias stored history.
        return SessionView(
            session_id=self.session_id,
            status="ended" if self.ended_at is not None else "active",
            created_at=self.created_at,
            ended_at=self.ended_at,
            product=self.product,
            state=state,
            total_turns=len(self.turns),
            turns=self.turns,
        ).model_copy(deep=True)


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, _Session] = {}
        self._lock = RLock()

    def create(self, request: CreateSession) -> SessionView:
        session = _Session(
            session_id=str(uuid4()),
            product=request.product.model_copy(deep=True),
            created_at=datetime.now(timezone.utc),
        )
        with self._lock:
            self._sessions[session.session_id] = session
            return session.snapshot()

    def _get(self, session_id: str) -> _Session:
        session = self._sessions.get(session_id)
        if session is None:
            raise MissingSession(session_id)
        return session

    def read(self, session_id: str) -> SessionView:
        with self._lock:
            return self._get(session_id).snapshot()

    def add_turn(self, session_id: str, turn: TurnInput) -> ProcessedTurn:
        with self._lock:
            session = self._get(session_id)
            if session.ended_at is not None:
                raise ClosedSession(session_id)
            analysis = analyse_turn(turn, session.product)
            processed = ProcessedTurn(
                turn_id=str(uuid4()),
                speaker=turn.speaker,
                text=turn.text,
                received_at=datetime.now(timezone.utc),
                analysis=analysis,
            )
            session.turns.append(processed)
            return processed.model_copy(deep=True)

    def end(self, session_id: str) -> SessionView:
        with self._lock:
            session = self._get(session_id)
            if session.ended_at is None:
                session.ended_at = datetime.now(timezone.utc)
            return session.snapshot()

    def read_transcripts(self, session_id: str) -> TranscriptHistory:
        with self._lock:
            session = self._get(session_id)
            return TranscriptHistory(
                session_id=session_id, segments=list(session.transcripts.values()), audio_pauses=session.audio_pauses,
            ).model_copy(deep=True)

    def check_active(self, session_id: str) -> None:
        with self._lock:
            if self._get(session_id).ended_at is not None:
                raise ClosedSession(session_id)

    def open_audio_source(self, session_id: str, source_id: str) -> None:
        with self._lock:
            self.check_active(session_id)
            session = self._get(session_id)
            if source_id in session.audio_sources or source_id in session.source_positions:
                raise TranscriptConflict("Use a new source ID for each continuous capture")
            session.audio_sources.add(source_id)

    def add_audio_pause(self, session_id: str, pause: AudioPause) -> None:
        with self._lock:
            self.check_active(session_id)
            self._get(session_id).audio_pauses.append(pause.model_copy(deep=True))

    def add_transcript(self, session_id: str, segment: TranscriptSegment) -> TranscriptRecord:
        with self._lock:
            session = self._get(session_id)
            if session.ended_at is not None:
                raise ClosedSession(session_id)
            key = (segment.source_id, segment.segment_id)
            previous = session.transcripts.get(key)
            if previous:
                if segment == previous.segment:
                    return previous.model_copy(deep=True)
                if previous.segment.is_final or segment.revision <= previous.segment.revision:
                    raise TranscriptConflict("Finalized or stale segment")
            record = TranscriptRecord(segment=segment.model_copy(deep=True))
            if segment.is_final:
                position = session.source_positions.get(segment.source_id)
                if position and segment.start_ms < position[0]:
                    raise TranscriptConflict("Source media clock moved backwards")
                last_word_end = position[1] if position else None
                record.gaps = word_gaps(segment, last_word_end)
                if segment.words:
                    last_word_end = max(last_word_end or 0, *(word.end_ms for word in segment.words))
                else:
                    # Without word timing, do not bridge an unknown interval.
                    last_word_end = None
                session.source_positions[segment.source_id] = (segment.start_ms, last_word_end)
                if segment.speaker is not None and not segment.review_required:
                    record.turn = self.add_turn(session_id, TurnInput(
                        speaker=segment.speaker, text=segment.text,
                    ))
            session.transcripts[key] = record
            return record.model_copy(deep=True)

    def review_transcript(self, session_id: str, review: TranscriptReview) -> TranscriptRecord:
        with self._lock:
            self.check_active(session_id)
            session = self._get(session_id)
            record = session.transcripts.get((review.source_id, review.segment_id))
            if record is None:
                raise TranscriptConflict("Transcript not found")
            if not record.segment.is_final:
                raise TranscriptConflict("Only final transcripts can be reviewed")
            if record.turn is not None:
                if record.reviewed_text == review.text and record.turn.speaker == review.speaker:
                    return record.model_copy(deep=True)
                raise TranscriptConflict("Transcript already analysed")
            record.turn = self.add_turn(session_id, TurnInput(speaker=review.speaker, text=review.text))
            record.reviewed_text = review.text
            return record.model_copy(deep=True)


def analyse_turn(turn: TurnInput, product: ProductContext | None = None) -> AnalysisResult:
    if turn.speaker == Speaker.SALESPERSON:
        # Current baseline looks at buyer signals only, not seller quality.
        return AnalysisResult(
            buying_signal=BuyingSignal.NEUTRAL,
            objections=[],
            evidence=[],
            recommendation=None,
        )
    detected = detect(turn.text)
    return AnalysisResult(
        buying_signal=detected.buying_signal,
        objections=detected.objections,
        evidence=detected.evidence,
        recommendation=recommend(turn.text, detected, product),
    )
