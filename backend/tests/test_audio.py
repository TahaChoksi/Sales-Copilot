from array import array
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.audio import AudioBuffer, AudioWindow, FRAME_BYTES
from app.main import create_app
from app.speech_schemas import TranscriptSegment
from app.transcription import LocalTranscriber


QUIET = bytes(FRAME_BYTES)
LOUD = (10000).to_bytes(2, "little", signed=True) * 1600


def test_audio_buffers_are_bounded_and_silence_is_not_transcribed():
    buffer = AudioBuffer()
    for _ in range(1000):
        assert buffer.feed(QUIET) == (None, None)
        assert len(buffer._buffer) <= FRAME_BYTES * 2
    assert buffer.finish() == (None, None)
    assert buffer.time_ms == 100000


def test_media_timing_and_long_pause_survive_endpoint_segmentation():
    buffer = AudioBuffer()
    buffer.feed(LOUD)
    buffer.feed(LOUD)
    windows = []
    for _ in range(30):
        window, pause = buffer.feed(QUIET)
        if window:
            windows.append(window)
        assert pause is None
    assert len(windows) == 1
    assert (windows[0].start_ms, windows[0].end_ms, windows[0].truncated) == (0, 2200, False)
    _, pause = buffer.feed(LOUD)
    assert (pause.start_ms, pause.end_ms) == (200, 3200)
    assert pause.payload()["duration_ms"] == 3000
    assert pause.basis == "pcm_rms"


def test_forced_cut_and_following_fragment_require_review():
    buffer = AudioBuffer()
    window = None
    for _ in range(200):
        candidate, _ = buffer.feed(LOUD)
        window = candidate or window
    assert window.truncated
    buffer.feed(LOUD)
    for _ in range(20):
        following, _ = buffer.feed(QUIET)
    assert following.truncated
    buffer.feed(LOUD)
    for _ in range(20):
        recovered, _ = buffer.feed(QUIET)
    assert not recovered.truncated


def test_manual_stop_flushes_audio_and_preserves_trailing_quiet_interval():
    buffer = AudioBuffer()
    buffer.feed(LOUD)
    for _ in range(5):
        buffer.feed(QUIET)
    window, pause = buffer.finish()
    assert window.truncated and len(window.pcm) == 6 * FRAME_BYTES
    assert pause.payload()["duration_ms"] == 500


@pytest.mark.parametrize("frame", [b"", b"x", bytes(FRAME_BYTES + 2)])
def test_invalid_pcm_frames_cannot_advance_the_clock(frame):
    buffer = AudioBuffer()
    with pytest.raises(ValueError):
        buffer.feed(frame)
    assert buffer.time_ms == 0


class FakeTranscriber:
    def __init__(self):
        self.windows = []

    def transcribe(self, window, source_id, segment_id, speaker, enable_coaching):
        self.windows.append(window)
        return TranscriptSegment(
            source_id=source_id, segment_id=segment_id, is_final=True, speaker=speaker,
            review_required=not enable_coaching or window.truncated,
            text="I can't afford it.", start_ms=window.start_ms, end_ms=window.end_ms,
            words=[dict(text="I", start_ms=window.start_ms, end_ms=window.start_ms + 50),
                   dict(text="can't", start_ms=window.start_ms + 50, end_ms=window.start_ms + 100),
                   dict(text="afford", start_ms=window.start_ms + 100, end_ms=window.start_ms + 150),
                   dict(text="it.", start_ms=window.start_ms + 150, end_ms=window.start_ms + 200)],
        )


def create_client(transcriber):
    client = TestClient(create_app(transcriber=transcriber))
    session_id = client.post("/api/v1/sessions", json={"product": {"name": "Synthetic software"}}).json()["session_id"]
    return client, session_id


def start_message(**changes):
    result = dict(type="start", source_id="remote-source", speaker="customer", sample_rate=16000,
                  consent_confirmed=True, enable_coaching=True)
    result.update(changes)
    return result


def send_frame(socket, frame):
    socket.send_bytes(frame)
    messages = []
    while True:
        event = socket.receive_json()
        messages.append(event)
        if event["type"] == "audio_ack":
            return messages


@pytest.mark.parametrize("coaching,speaker,expected_turns", [
    (True, "customer", 1), (False, "customer", 0), (True, None, 0), (True, "salesperson", 1),
])
def test_audio_to_final_transcript_preserves_speaker_and_coaching_gate(coaching, speaker, expected_turns):
    transcriber = FakeTranscriber()
    client, session_id = create_client(transcriber)
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/audio") as socket:
        socket.send_json(start_message(enable_coaching=coaching, speaker=speaker))
        assert socket.receive_json()["type"] == "audio_ready"
        messages = []
        for frame in [LOUD, LOUD, *([QUIET] * 20)]:
            messages += send_frame(socket, frame)
        records = [event["data"] for event in messages if event["type"] == "transcript_processed"]
        assert len(records) == 1
        assert bool(records[0]["turn"]) == bool(expected_turns)
        if speaker == "salesperson":
            assert records[0]["turn"]["analysis"]["recommendation"] is None
        socket.send_json({"type": "stop"})
        assert socket.receive_json()["type"] == "audio_pause"
        assert socket.receive_json()["type"] == "audio_stopped"
    history = client.get(f"/api/v1/sessions/{session_id}/transcripts").json()
    assert len(history["segments"]) == 1
    assert history["audio_pauses"][0]["duration_ms"] == 2000
    assert client.get(f"/api/v1/sessions/{session_id}").json()["total_turns"] == expected_turns


def test_disabled_speech_does_not_download_or_process_audio():
    client, session_id = create_client(None)
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/audio") as socket:
        assert socket.receive_json()["code"] == "speech_unavailable"


@pytest.mark.parametrize("changes", [{"consent_confirmed": False}, {"sample_rate": 48000}, {"speaker": "guessed"}])
def test_invalid_audio_configuration_is_rejected(changes):
    client, session_id = create_client(FakeTranscriber())
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/audio") as socket:
        socket.send_json(start_message(**changes))
        assert socket.receive_json()["code"] == "invalid_audio_start"
    assert client.get(f"/api/v1/sessions/{session_id}").json()["total_turns"] == 0


def test_wrong_audio_frame_size_closes_instead_of_inventing_timing():
    client, session_id = create_client(FakeTranscriber())
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/audio") as socket:
        socket.send_json(start_message())
        assert socket.receive_json()["type"] == "audio_ready"
        socket.send_bytes(b"incorrect")
        assert socket.receive_json()["code"] == "invalid_audio_frame"
        with pytest.raises(WebSocketDisconnect):
            socket.receive_json()


@pytest.mark.parametrize("origin", ["https://untrusted.example", "chrome-extension://unapproved"])
def test_browser_capture_requires_explicit_origin_configuration(origin):
    client, session_id = create_client(FakeTranscriber())
    with pytest.raises(WebSocketDisconnect) as caught:
        with client.websocket_connect(f"/api/v1/sessions/{session_id}/audio", headers={"origin": origin}):
            pass
    assert caught.value.code == 1008


def test_known_extension_origin_can_connect(monkeypatch):
    monkeypatch.setenv("SALES_COPILOT_EXTENSION_ORIGIN", "chrome-extension://test-extension")
    client, session_id = create_client(FakeTranscriber())
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/audio", headers={"origin": "chrome-extension://test-extension"}) as socket:
        socket.send_json(start_message())
        assert socket.receive_json()["type"] == "audio_ready"
        socket.send_json({"type": "stop"})
        assert socket.receive_json()["type"] == "audio_stopped"


def test_missing_ended_and_reused_audio_sources_are_rejected():
    client, session_id = create_client(FakeTranscriber())
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/v1/sessions/missing/audio"):
            pass
    path = f"/api/v1/sessions/{session_id}/audio"
    with client.websocket_connect(path) as socket:
        socket.send_json(start_message())
        assert socket.receive_json()["type"] == "audio_ready"
        socket.send_json({"type": "stop"})
        assert socket.receive_json()["type"] == "audio_stopped"
    with client.websocket_connect(path) as socket:
        socket.send_json(start_message())
        assert socket.receive_json()["code"] == "invalid_audio_start"
    client.post(f"/api/v1/sessions/{session_id}/end")
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(path):
            pass


def test_transcriber_uses_original_clock_and_withholds_low_quality(monkeypatch):
    pytest.importorskip("numpy")
    import threading
    model = LocalTranscriber.__new__(LocalTranscriber)
    model._lock = threading.Lock()
    options = {}

    def transcribe(samples, **kwargs):
        options.update(kwargs)
        return iter([SimpleNamespace(text=" I can't afford it.", no_speech_prob=0.1, avg_logprob=-0.2,
                    words=[SimpleNamespace(word=" I", start=0.1, end=0.2, probability=0.9),
                           SimpleNamespace(word=" can't", start=0.2, end=0.4, probability=0.4),
                           SimpleNamespace(word=" afford", start=0.4, end=0.6, probability=0.9),
                           SimpleNamespace(word=" it.", start=0.6, end=0.7, probability=0.9)])]), None

    model._model = SimpleNamespace(transcribe=transcribe)
    result = model.transcribe(AudioWindow(LOUD * 10, 5000, 6000), "source", "one", "customer", True)
    assert result.words[0].start_ms == 5100
    assert result.words[0].confidence == 0.9
    assert result.text == " I can't afford it."
    assert result.review_required
    assert options["word_timestamps"] and options["vad_filter"]
    assert options["language"] == "en" and options["task"] == "transcribe"
    assert not options["condition_on_previous_text"]


def test_transcription_failure_does_not_echo_sensitive_provider_exception():
    class BrokenTranscriber:
        def transcribe(self, *args):
            raise RuntimeError("synthetic-private-transcript-marker")
    client, session_id = create_client(BrokenTranscriber())
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/audio") as socket:
        socket.send_json(start_message())
        assert socket.receive_json()["type"] == "audio_ready"
        for _ in range(2):
            send_frame(socket, LOUD)
        for _ in range(19):
            send_frame(socket, QUIET)
        socket.send_bytes(QUIET)
        error = socket.receive_json()
        assert error["code"] == "transcription_failed"
        assert "synthetic-private-transcript-marker" not in str(error)
    assert client.get(f"/api/v1/sessions/{session_id}").json()["total_turns"] == 0


def test_ending_session_during_capture_blocks_new_audio():
    client, session_id = create_client(FakeTranscriber())
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/audio") as socket:
        socket.send_json(start_message())
        assert socket.receive_json()["type"] == "audio_ready"
        client.post(f"/api/v1/sessions/{session_id}/end")
        socket.send_bytes(LOUD)
        with pytest.raises(WebSocketDisconnect) as caught:
            socket.receive_json()
        assert caught.value.code == 1008


def test_transcript_rest_validation_review_and_legacy_contract():
    client, session_id = create_client(FakeTranscriber())
    path = f"/api/v1/sessions/{session_id}/transcripts"
    request = dict(source_id="remote", segment_id="one", is_final=True, review_required=True,
                   text="I am interested.", start_ms=0, end_ms=1000, words=[])
    added = client.post(path, json=request)
    assert added.status_code == 200
    assert added.json()["turn"] is None
    review = dict(source_id="remote", segment_id="one", speaker="customer", text="I am not interested.")
    reviewed = client.post(f"{path}/review", json=review)
    assert reviewed.status_code == 200
    assert reviewed.json()["segment"]["text"] == request["text"]
    assert reviewed.json()["turn"]["analysis"]["buying_signal"] == "refusal"
    assert client.post(f"{path}/review", json=review).json() == reviewed.json()
    assert client.post(f"{path}/review", json={**review, "text": " "}).status_code == 422
    assert client.post(path, json={**request, "end_ms": -1}).status_code == 422
    assert client.post("/api/v1/sessions/missing/transcripts", json=request).status_code == 404
    assert client.get("/api/v1/sessions/missing/transcripts").status_code == 404
    assert client.post("/api/v1/sessions/missing/transcripts/review", json=review).status_code == 404
    assert client.get(path).json()["segments"][0] == reviewed.json()
    legacy = client.get(f"/api/v1/sessions/{session_id}").json()
    assert "transcripts" not in legacy and "audio_pauses" not in legacy
    assert legacy["total_turns"] == 1
    client.post(f"/api/v1/sessions/{session_id}/end")
    assert client.post(path, json=request).status_code == 409
    assert client.post(f"{path}/review", json=review).status_code == 409


def test_audio_handshake_owns_speaker_and_coaching_gate_even_if_adapter_guesses():
    class GuessingAdapter(FakeTranscriber):
        def transcribe(self, window, source_id, segment_id, speaker, enable_coaching):
            return super().transcribe(window, "wrong-source", "wrong-segment", "customer", True)
    client, session_id = create_client(GuessingAdapter())
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/audio") as socket:
        socket.send_json(start_message(speaker=None, enable_coaching=False))
        assert socket.receive_json()["type"] == "audio_ready"
        for frame in [LOUD, LOUD, *([QUIET] * 20)]:
            send_frame(socket, frame)
        socket.send_json({"type": "stop"})
        while socket.receive_json()["type"] != "audio_stopped":
            pass
    record = client.get(f"/api/v1/sessions/{session_id}/transcripts").json()["segments"][0]
    assert record["segment"]["source_id"] == "remote-source"
    assert record["segment"]["speaker"] is None
    assert record["segment"]["review_required"]
    assert record["turn"] is None
