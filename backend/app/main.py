"""Sales Copilot v0.1 API.

Run locally: python -m uvicorn app.main:app --reload --host 127.0.0.1
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError

from app.schemas import (
    AnalyseInput, AnalysisResult, CreateSession, ErrorEvent,
    ProcessedTurn, SessionView, TurnInput,
)
from app.store import ClosedSession, MissingSession, SessionStore, analyse_turn
from app.speech_routes import speech_router
from app.transcription import LocalTranscriber, Transcriber


def create_app(transcriber: Transcriber | None = None) -> FastAPI:
    app = FastAPI(
        title="AI Sales Copilot (Prototype)",
        version="0.1.0",
        description="Local text coaching with optional local audio transcription. Not production-ready.",
    )
    store = SessionStore()
    model_path = os.environ.get("SALES_COPILOT_SPEECH_MODEL")
    if transcriber is None and model_path:
        transcriber = LocalTranscriber(Path(model_path))
    app.include_router(speech_router(
        store, transcriber, os.environ.get("SALES_COPILOT_EXTENSION_ORIGIN"),
    ))

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": "0.1.0"}

    @app.post("/api/v1/analyse", response_model=AnalysisResult)
    def analyse(request: AnalyseInput) -> AnalysisResult:
        return analyse_turn(TurnInput(speaker=request.speaker, text=request.text), request.product)

    @app.post("/api/v1/sessions", response_model=SessionView, status_code=status.HTTP_201_CREATED)
    def create_session(request: CreateSession) -> SessionView:
        return store.create(request)

    @app.get("/api/v1/sessions/{session_id}", response_model=SessionView)
    def get_session(session_id: str) -> SessionView:
        try:
            return store.read(session_id)
        except MissingSession:
            raise HTTPException(status_code=404, detail="Session not found") from None

    @app.post("/api/v1/sessions/{session_id}/turns", response_model=ProcessedTurn)
    def add_turn(session_id: str, request: TurnInput) -> ProcessedTurn:
        try:
            return store.add_turn(session_id, request)
        except MissingSession:
            raise HTTPException(status_code=404, detail="Session not found") from None
        except ClosedSession:
            raise HTTPException(status_code=409, detail="Session already ended") from None

    @app.post("/api/v1/sessions/{session_id}/end", response_model=SessionView)
    def end_session(session_id: str) -> SessionView:
        try:
            return store.end(session_id)
        except MissingSession:
            raise HTTPException(status_code=404, detail="Session not found") from None

    @app.websocket("/api/v1/sessions/{session_id}/stream")
    async def stream_turns(websocket: WebSocket, session_id: str) -> None:
        # This only accepts *text* transcript events; raw audio is a later phase.
        # Check session existence before handshake.
        try:
            existing = store.read(session_id)
        except MissingSession:
            await websocket.close(code=1008, reason="Unknown session")
            return
        if existing.status == "ended":
            await websocket.close(code=1008, reason="Session ended")
            return
        await websocket.accept()
        try:
            while True:
                try:
                    payload = await websocket.receive_json()
                    turn = TurnInput.model_validate(payload)
                except (ValueError, TypeError, ValidationError):
                    await websocket.send_json(
                        ErrorEvent(code="invalid_turn", message="Send JSON with speaker and nonblank text").model_dump()
                    )
                    continue
                try:
                    result = store.add_turn(session_id, turn)
                except MissingSession:
                    await websocket.close(code=1008, reason="Unknown session")
                    return
                except ClosedSession:
                    await websocket.close(code=1008, reason="Session ended")
                    return
                await websocket.send_json({"type": "turn_processed", "data": result.model_dump(mode="json")})
        except WebSocketDisconnect:
            return

    return app


app = create_app()
