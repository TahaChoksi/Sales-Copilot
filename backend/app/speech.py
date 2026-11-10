"""Transcript timing helpers, independent of ASR and coaching interpretation."""

from app.speech_schemas import TranscriptSegment, WordGap


MIN_WORD_GAP_MS = 500  # A display threshold, not a validated hesitation threshold.


def word_gaps(segment: TranscriptSegment, previous_end_ms: int | None = None) -> list[WordGap]:
    gaps = []
    end = previous_end_ms
    for word in segment.words:
        if end is not None and word.start_ms - end >= MIN_WORD_GAP_MS:
            gaps.append(WordGap(source_id=segment.source_id, start_ms=end,
                                 end_ms=word.start_ms, duration_ms=word.start_ms - end))
        end = max(end or 0, word.end_ms)
    return gaps
