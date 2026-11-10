"""Bounded PCM buffering and measured low-energy intervals, not emotion inference."""

from array import array
from dataclasses import dataclass
from math import sqrt
from sys import byteorder


SAMPLE_RATE = 16000
FRAME_SAMPLES = 1600  # 100 ms
FRAME_BYTES = FRAME_SAMPLES * 2
FRAME_MS = 100
ENDPOINT_MS = 2000
MAX_UTTERANCE_MS = 20000
LOW_ENERGY_THRESHOLD = 0.005  # Normalized RMS; heuristic, not voice activity proof.


@dataclass(frozen=True)
class AudioWindow:
    pcm: bytes
    start_ms: int
    end_ms: int
    truncated: bool = False


@dataclass(frozen=True)
class LowEnergyInterval:
    start_ms: int
    end_ms: int
    rms_threshold: float = LOW_ENERGY_THRESHOLD
    basis: str = "pcm_rms"

    def payload(self) -> dict:
        return dict(start_ms=self.start_ms, end_ms=self.end_ms,
                    duration_ms=self.end_ms - self.start_ms,
                    rms_threshold=self.rms_threshold, basis=self.basis)


class AudioBuffer:
    """One continuous source. Never infer elapsed audio from network arrival time."""

    def __init__(self) -> None:
        self.time_ms = 0
        self._buffer = bytearray()
        self._start_ms = 0
        self._active = False
        self._heard_audio = False
        self._quiet_start: int | None = None
        self._continued_cut = False

    def feed(self, pcm: bytes) -> tuple[AudioWindow | None, LowEnergyInterval | None]:
        if len(pcm) != FRAME_BYTES:
            raise ValueError("Expected exactly 100 ms of mono PCM16 at 16000 Hz")
        samples = array("h")
        samples.frombytes(pcm)
        if byteorder != "little":
            samples.byteswap()
        rms = sqrt(sum(sample * sample for sample in samples) / len(samples)) / 32768
        loud = rms >= LOW_ENERGY_THRESHOLD
        start, self.time_ms = self.time_ms, self.time_ms + FRAME_MS
        pause = None
        if loud:
            if self._quiet_start is not None and start - self._quiet_start >= 500:
                pause = LowEnergyInterval(self._quiet_start, start)
            self._quiet_start = None
            self._heard_audio = True
        elif self._heard_audio and self._quiet_start is None:
            self._quiet_start = start
        if not self._active:
            # Keep 200 ms of pre-roll, so a quiet word onset isn't immediately lost.
            self._buffer.extend(pcm)
            if len(self._buffer) > FRAME_BYTES * 2:
                del self._buffer[:-FRAME_BYTES * 2]
            self._start_ms = self.time_ms - len(self._buffer) // (SAMPLE_RATE * 2 // 1000)
            if not loud:
                return None, pause
            self._active = True
        else:
            self._buffer.extend(pcm)
        natural_end = self._quiet_start is not None and self.time_ms - self._quiet_start >= ENDPOINT_MS
        forced_end = self.time_ms - self._start_ms >= MAX_UTTERANCE_MS
        if natural_end or forced_end:
            window = AudioWindow(bytes(self._buffer), self._start_ms, self.time_ms,
                                 truncated=self._continued_cut or forced_end)
            self._continued_cut = forced_end and not natural_end
            self._buffer.clear()
            self._active = False
            return window, pause
        return None, pause

    def finish(self) -> tuple[AudioWindow | None, LowEnergyInterval | None]:
        pause = None
        if self._quiet_start is not None and self.time_ms - self._quiet_start >= 500:
            pause = LowEnergyInterval(self._quiet_start, self.time_ms)
        # A manually stopped phrase may be incomplete: review before coaching.
        window = AudioWindow(bytes(self._buffer), self._start_ms, self.time_ms, truncated=True) if self._active else None
        self._buffer.clear()
        self._active = False
        self._quiet_start = None
        return window, pause
