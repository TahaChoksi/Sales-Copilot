"""Additive transcript and local-audio routes; existing v1 text APIs stay intact."""

import asyncio
import json

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.audio import AudioBuffer, AudioWindow, FRAME_BYTES, LowEnergyInterval
from app.speech_schemas import AudioPause, AudioStart, TranscriptHistory, TranscriptRecord, TranscriptReview, TranscriptSegment
from app.store import ClosedSession, MissingSession, SessionStore, TranscriptConflict
from app.transcription import Transcriber


def speech_router(store: SessionStore, transcriber: Transcriber | None, extension_origin: str | None) -> APIRouter:
    router = APIRouter(prefix="/api/v1/sessions")

    @router.get("/{session_id}/transcripts", response_model=TranscriptHistory)
    def read_transcripts(session_id: str) -> TranscriptHistory:
        try:
            return store.read_transcripts(session_id)
        except MissingSession:
            raise HTTPException(404, "Session not found") from None

    @router.post("/{session_id}/transcripts", response_model=TranscriptRecord)
    def add_transcript(session_id: str, request: TranscriptSegment) -> TranscriptRecord:
        try:
            return store.add_transcript(session_id, request)
        except MissingSession:
            raise HTTPException(404, "Session not found") from None
        except ClosedSession:
            raise HTTPException(409, "Session already ended") from None
        except TranscriptConflict:
            raise HTTPException(409, "Finalized, stale or out-of-order transcript") from None

    @router.post("/{session_id}/transcripts/review", response_model=TranscriptRecord)
    def review_transcript(session_id: str, request: TranscriptReview) -> TranscriptRecord:
        try:
            return store.review_transcript(session_id, request)
        except MissingSession:
            raise HTTPException(404, "Session not found") from None
        except ClosedSession:
            raise HTTPException(409, "Session already ended") from None
        except TranscriptConflict:
            raise HTTPException(409, "Only an unanalysed final transcript can be reviewed") from None

    @router.websocket("/{session_id}/audio")
    async def audio_stream(websocket: WebSocket, session_id: str) -> None:
        # Browser callers must use the explicitly configured extension origin.
        # Missing Origin supports native local clients; this is not authentication.
        origin = websocket.headers.get("origin")
        if origin and origin != extension_origin:
            await websocket.close(code=1008, reason="Unapproved capture origin")
            return
        try:
            store.check_active(session_id)
        except (MissingSession, ClosedSession):
            await websocket.close(code=1008, reason="Session unavailable")
            return
        await websocket.accept()
        if transcriber is None:
            await websocket.send_json({"type": "error", "code": "speech_unavailable",
                                       "message": "Start the server with a local speech model"})
            await websocket.close(code=1013)
            return
        try:
            try:
                start = AudioStart.model_validate_json(await websocket.receive_text())
                store.open_audio_source(session_id, start.source_id)
            except (ValueError, KeyError, ValidationError, TranscriptConflict):
                await websocket.send_json({"type": "error", "code": "invalid_audio_start"})
                await websocket.close(code=1008)
                return
            buffer = AudioBuffer()
            sequence = 0

            async def publish(window: AudioWindow | None, pause: LowEnergyInterval | None) -> None:
                nonlocal sequence
                if pause:
                    observation = AudioPause(source_id=start.source_id, **pause.payload())
                    store.add_audio_pause(session_id, observation)
                    await websocket.send_json({"type": "audio_pause", "data": observation.model_dump()})
                if window:
                    sequence += 1
                    result = await asyncio.to_thread(
                        transcriber.transcribe, window, start.source_id, f"audio-{sequence}",
                        start.speaker, start.enable_coaching,
                    )
                    # Check lifecycle again after potentially slow inference.
                    store.check_active(session_id)
                    if result is not None:
                        # Source identity and the coaching opt-in belong to the
                        # capture handshake, never to provider guesses/defaults.
                        result = result.model_copy(update={
                            "source_id": start.source_id, "segment_id": f"audio-{sequence}",
                            "speaker": start.speaker,
                            "review_required": result.review_required or not start.enable_coaching,
                        })
                        record = store.add_transcript(session_id, result)
                        await websocket.send_json({"type": "transcript_processed", "data": record.model_dump(mode="json")})

            await websocket.send_json({"type": "audio_ready", "frame_bytes": FRAME_BYTES, "sample_rate": 16000})
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    return  # Abrupt disconnect discards unconfirmed buffered audio.
                store.check_active(session_id)
                if message.get("bytes") is not None:
                    pcm = message["bytes"]
                    if len(pcm) != FRAME_BYTES:
                        await websocket.send_json({"type": "error", "code": "invalid_audio_frame"})
                        await websocket.close(code=1008)
                        return
                    await publish(*buffer.feed(pcm))
                    await websocket.send_json({"type": "audio_ack", "received_ms": buffer.time_ms})
                else:
                    try:
                        command = json.loads(message.get("text") or "")
                    except ValueError:
                        command = None
                    if command != {"type": "stop"}:
                        await websocket.send_json({"type": "error", "code": "invalid_audio_command"})
                        await websocket.close(code=1008)
                        return
                    await publish(*buffer.finish())
                    await websocket.send_json({"type": "audio_stopped", "received_ms": buffer.time_ms})
                    await websocket.close(code=1000)
                    return
        except (MissingSession, ClosedSession):
            await websocket.close(code=1008, reason="Session ended")
        except TranscriptConflict:
            await websocket.send_json({"type": "error", "code": "transcript_conflict"})
            await websocket.close(code=1008)
        except WebSocketDisconnect:
            return
        except Exception:
            # Provider exceptions can embed transcript/audio data; never log them.
            await websocket.send_json({"type": "error", "code": "transcription_failed",
                                       "message": "Transcription failed; stop capture and review the source"})
            await websocket.close(code=1011)

    return router
