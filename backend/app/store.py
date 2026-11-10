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
from app.schemas import (
    AnalysisResult, BuyingSignal, ConversationState, CreateSession, ProcessedTurn,
    ProductContext, SessionView, Speaker, TurnInput,
)


class MissingSession(Exception):
    pass


class ClosedSession(Exception):
    pass


@dataclass
class _Session:
    session_id: str
    created_at: datetime
    product: ProductContext
    ended_at: datetime | None = None
    turns: list[ProcessedTurn] = field(default_factory=list)

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
