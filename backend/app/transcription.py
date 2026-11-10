"""Opt-in local ASR. No network downloads or audio files in the request path."""

from pathlib import Path
from threading import Lock
from typing import Protocol

from app.audio import AudioWindow
from app.speech_schemas import TimedWord, TranscriptSegment
from app.schemas import Speaker


class Transcriber(Protocol):
    def transcribe(self, window: AudioWindow, source_id: str, segment_id: str,
                   speaker: Speaker | None, enable_coaching: bool) -> TranscriptSegment | None: ...


class LocalTranscriber:
    def __init__(self, model_path: Path) -> None:
        # Optional dependencies are imported only when speech is explicitly enabled.
        import onnxruntime
        from faster_whisper import WhisperModel

        onnxruntime.disable_telemetry_events()
        if not model_path.is_dir():
            raise ValueError("Local speech model directory is unavailable")
        self._model = WhisperModel(str(model_path), device="cpu", compute_type="int8", local_files_only=True)
        self._lock = Lock()

    def transcribe(
        self, window: AudioWindow, source_id: str, segment_id: str,
        speaker: Speaker | None, enable_coaching: bool,
    ) -> TranscriptSegment | None:
        import numpy as np

        samples = np.frombuffer(window.pcm, dtype="<i2").astype(np.float32) / 32768.0
        with self._lock:
            segments, _ = self._model.transcribe(
                samples, language="en", task="transcribe", word_timestamps=True,
                condition_on_previous_text=False, temperature=0.0, beam_size=5,
                vad_filter=True, vad_parameters={"min_silence_duration_ms": 500},
            )
            segments = list(segments)  # Inference is lazy; keep it inside the lock.
        text = "".join(segment.text for segment in segments)
        if not text.strip():
            return None
        words = []
        uncertain = window.truncated or not enable_coaching
        for segment in segments:
            # Provider scores are heuristics, not calibrated correctness estimates.
            uncertain |= segment.no_speech_prob > 0.5 or segment.avg_logprob < -1.0
            for word in segment.words or []:
                token = word.word.strip()
                if not token:
                    continue
                start = max(window.start_ms, window.start_ms + round(word.start * 1000))
                end = min(window.end_ms, window.start_ms + round(word.end * 1000))
                if end < start:
                    uncertain = True
                    continue
                words.append(TimedWord(text=token, start_ms=start, end_ms=end,
                                       confidence=word.probability))
                uncertain |= word.probability < 0.6
        uncertain |= not words
        return TranscriptSegment(
            source_id=source_id, segment_id=segment_id, is_final=True,
            speaker=speaker, review_required=bool(uncertain), text=text,
            start_ms=window.start_ms, end_ms=window.end_ms, words=words,
        )
