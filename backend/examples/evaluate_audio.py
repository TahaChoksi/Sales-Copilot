"""Evaluate a short, authorised local audio clip without printing its transcript.

Usage: python backend/examples/evaluate_audio.py clip.wav reference.txt
Audio and references remain local; do not commit customer files or use them for training.
"""

import argparse
import hashlib
import json
from pathlib import Path
from time import monotonic

from app.audio import AudioBuffer, AudioWindow, FRAME_BYTES
from app.speech import word_gaps
from app.speech_evaluation import word_error_counts
from app.transcription import LocalTranscriber


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("reference", type=Path)
    parser.add_argument("--model", type=Path, default=Path(".models/faster-whisper-small.en"))
    parser.add_argument("--streaming", action="store_true", help="Evaluate the same buffering/endpoint path as call capture")
    args = parser.parse_args()
    try:
        report = evaluate_clip(args.audio, args.reference, args.model, args.streaming)
    except (OSError, ValueError, RuntimeError, ImportError):
        parser.exit(2, "Could not evaluate clip; check dependencies, model, reference and audio (maximum 20 seconds).\n")
    print(json.dumps(report, indent=2))


def evaluate_clip(audio: Path, reference: Path, model_path: Path, streaming: bool = False):
    from faster_whisper.audio import decode_audio
    samples = decode_audio(str(audio), sampling_rate=16000)
    duration_ms = round(len(samples) / 16)
    if not 0 < duration_ms <= 20000:
        raise ValueError("Use a nonempty clip of at most 20 seconds")
    model = LocalTranscriber(model_path)
    pcm = (samples.clip(-1, 1) * 32767).astype("<i2").tobytes()
    started = monotonic()
    windows = [AudioWindow(pcm, 0, duration_ms)]
    pauses = []
    if streaming:
        windows = []
        buffer = AudioBuffer()
        for offset in range(0, len(pcm), FRAME_BYTES):
            window, pause = buffer.feed(pcm[offset:offset + FRAME_BYTES].ljust(FRAME_BYTES, b"\x00"))
            if window:
                windows.append(window)
            if pause:
                pauses.append(pause.payload())
        window, pause = buffer.finish()
        if window:
            windows.append(window)
        if pause:
            pauses.append(pause.payload())
    results = []
    for i, window in enumerate(windows):
        result = model.transcribe(window, "offline", f"clip-{i}", None, False)
        if result:
            results.append(result)
    report = word_error_counts(reference.read_text(encoding="utf-8"), " ".join(result.text for result in results))
    report.update(duration_ms=duration_ms, transcription_seconds=round(monotonic() - started, 3),
                  returned_words=sum(len(result.words) for result in results),
                  low_energy_intervals=pauses,
                  estimated_word_gaps=[gap.model_dump() for result in results for gap in word_gaps(result)],
                  audio_sha256=hashlib.sha256(audio.read_bytes()).hexdigest())
    return report


if __name__ == "__main__":
    main()
