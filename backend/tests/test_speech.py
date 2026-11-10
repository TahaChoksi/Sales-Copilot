"""Synthetic transcript/timing tests; no recordings or speech model required."""

import pytest
from pydantic import ValidationError

from app.schemas import CreateSession
from app.speech_schemas import TranscriptSegment
from app.store import ClosedSession, MissingSession, SessionStore, TranscriptConflict


def segment(**overrides):
    data = dict(source_id="remote-channel-1", segment_id="utterance-1", revision=0,
                is_final=True, speaker="customer", review_required=False,
                text="Um, I can't afford it.", start_ms=0, end_ms=3000,
                words=[dict(text="Um,", start_ms=0, end_ms=200),
                       dict(text="I", start_ms=1200, end_ms=1300),
                       dict(text="can't", start_ms=1400, end_ms=1600),
                       dict(text="afford", start_ms=1700, end_ms=2000),
                       dict(text="it.", start_ms=2100, end_ms=2300)])
    data.update(overrides)
    return TranscriptSegment.model_validate(data)


def session():
    store = SessionStore()
    view = store.create(CreateSession(product={"name": "Synthetic software"}))
    return store, view.session_id


def test_final_transcript_preserves_words_fillers_and_timing_without_inferring_emotion():
    store, session_id = session()
    request = segment()
    result = store.add_transcript(session_id, request)
    assert result.segment == request
    assert result.turn.analysis.objections == ["price"]
    assert len(result.gaps) == 1
    gap = result.gaps[0]
    assert (gap.start_ms, gap.end_ms, gap.duration_ms) == (200, 1200, 1000)
    assert gap.basis == "word_timestamps"
    assert "hesitation" not in result.model_dump_json()
    assert store.read(session_id).total_turns == 1
    assert store.read_transcripts(session_id).segments == [result]


def test_partial_revisions_never_trigger_coaching_and_final_is_processed_once():
    store, session_id = session()
    partial = segment(is_final=False)
    first = store.add_transcript(session_id, partial)
    assert first.turn is None
    assert first.gaps == []
    assert store.read(session_id).total_turns == 0
    revised = segment(is_final=False, revision=1, text="Um, I cannot afford it.", words=[])
    store.add_transcript(session_id, revised)
    final = segment(revision=2)
    accepted = store.add_transcript(session_id, final)
    assert store.add_transcript(session_id, final) == accepted
    assert store.read(session_id).total_turns == 1
    assert len(store.read_transcripts(session_id).segments) == 1
    with pytest.raises(TranscriptConflict):
        store.add_transcript(session_id, segment(revision=3))


@pytest.mark.parametrize("kwargs", [{"speaker": None}, {"review_required": True}])
def test_uncertain_transcript_or_speaker_keeps_timing_but_withholds_analysis(kwargs):
    store, session_id = session()
    result = store.add_transcript(session_id, segment(**kwargs))
    assert result.turn is None
    assert len(result.gaps) == 1
    assert store.read(session_id).total_turns == 0


def test_word_gap_threshold_and_overlap_are_handled_without_negative_pauses():
    store, session_id = session()
    request = segment(text="yes okay sure", end_ms=1800, words=[
        dict(text="yes", start_ms=0, end_ms=1000),
        dict(text="okay", start_ms=800, end_ms=1100),
        dict(text="sure", start_ms=1599, end_ms=1800),
    ])
    assert store.add_transcript(session_id, request).gaps == []


def test_intersegment_gaps_use_media_clock_and_stay_within_source():
    store, session_id = session()
    store.add_transcript(session_id, segment())
    next_segment = segment(segment_id="utterance-2", text="Okay", start_ms=4000,
                           end_ms=4500, words=[dict(text="Okay", start_ms=4000, end_ms=4400)])
    result = store.add_transcript(session_id, next_segment)
    assert [(gap.start_ms, gap.end_ms) for gap in result.gaps] == [(2300, 4000)]
    other_source = next_segment.model_copy(update={"source_id": "local-channel"})
    assert store.add_transcript(session_id, other_source).gaps == []


def test_stale_revisions_and_changed_duplicate_are_rejected_without_mutation():
    store, session_id = session()
    store.add_transcript(session_id, segment(is_final=False, revision=2))
    for request in [segment(revision=1), segment(is_final=False, revision=2, review_required=True)]:
        with pytest.raises(TranscriptConflict):
            store.add_transcript(session_id, request)
    assert store.read(session_id).total_turns == 0
    assert store.read_transcripts(session_id).segments[0].segment.revision == 2


def test_final_timestamps_cannot_move_backwards_within_source():
    store, session_id = session()
    store.add_transcript(session_id, segment(start_ms=500, words=[]))
    with pytest.raises(TranscriptConflict):
        store.add_transcript(session_id, segment(segment_id="older"))
    assert store.read(session_id).total_turns == 1


def test_transcript_records_and_requests_do_not_alias_store_state():
    store, session_id = session()
    request = segment()
    returned = store.add_transcript(session_id, request)
    request.words.clear()
    returned.gaps.clear()
    returned.segment.text = "mutated"
    history = store.read_transcripts(session_id)
    assert history.segments[0].segment.text == "Um, I can't afford it."
    assert len(history.segments[0].gaps) == 1
    history.segments.clear()
    assert len(store.read_transcripts(session_id).segments) == 1


def test_session_lifecycle_applies_to_transcripts():
    store, session_id = session()
    with pytest.raises(MissingSession):
        store.add_transcript("missing", segment())
    with pytest.raises(MissingSession):
        store.read_transcripts("missing")
    store.end(session_id)
    with pytest.raises(ClosedSession):
        store.add_transcript(session_id, segment())


@pytest.mark.parametrize("changes", [
    {"start_ms": -1}, {"end_ms": 0}, {"start_ms": 4000},
    {"revision": -1}, {"text": " "}, {"source_id": " "},
    {"words": [dict(text="absent", start_ms=0, end_ms=100)]},
    {"words": [dict(text="Um,", start_ms=0, end_ms=4000)]},
    {"words": [dict(text="Um,", start_ms=200, end_ms=100)]},
    {"words": [dict(text="Um,", start_ms=0, end_ms=100, confidence=1.1)]},
    {"words": [dict(text="I", start_ms=1200, end_ms=1300), dict(text="Um,", start_ms=0, end_ms=100)]},
])
def test_invalid_transcript_inputs_are_rejected(changes):
    with pytest.raises(ValidationError):
        segment(**changes)


def test_word_error_measurement_keeps_negation_and_reports_insertions_deletions():
    from app.speech_evaluation import word_error_counts
    assert word_error_counts("I cannot buy", "I can buy")["substitutions"] == 1
    assert word_error_counts("I am not buying", "I am buying")["deletions"] == 1
    assert word_error_counts("I buy", "I will buy")["insertions"] == 1
    assert word_error_counts("I buy", "I will buy")["word_error_rate"] == 0.5
    assert word_error_counts("I can’t buy.", "i can't buy!")["word_error_rate"] == 0
    assert word_error_counts("", "invented words")["word_error_rate"] is None
    assert word_error_counts("", "invented words")["insertions"] == 2
    assert word_error_counts("I will buy", "")["word_error_rate"] == 1


def test_manual_review_preserves_original_and_analyzes_corrected_text_only_once():
    from app.speech_schemas import TranscriptReview
    store, session_id = session()
    original = segment(text="I am interested.", words=[], review_required=True, speaker=None)
    store.add_transcript(session_id, original)
    review = TranscriptReview(source_id=original.source_id, segment_id=original.segment_id,
                              speaker="customer", text="I am not interested.")
    corrected = store.review_transcript(session_id, review)
    assert corrected.segment.text == "I am interested."
    assert corrected.reviewed_text == "I am not interested."
    assert corrected.turn.text == "I am not interested."
    assert corrected.turn.analysis.buying_signal == "refusal"
    assert corrected.turn.analysis.recommendation is None
    assert store.review_transcript(session_id, review) == corrected
    assert store.read(session_id).total_turns == 1
    with pytest.raises(TranscriptConflict):
        store.review_transcript(session_id, review.model_copy(update={"text": "I will buy"}))
