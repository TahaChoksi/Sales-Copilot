import pytest

from app.detection import detect
from app.schemas import BuyingSignal, Objection


def test_expensive_price_objection():
    result = detect("I like the course, but £99 a month is too expensive.")
    assert result.buying_signal == BuyingSignal.POSITIVE_INTEREST
    assert Objection.PRICE in result.objections
    assert "too expensive" in result.evidence


def test_plain_price_question_not_price_objection():
    result = detect("How much does the course cost?")
    assert result.buying_signal == BuyingSignal.INFORMATION_REQUEST
    assert result.objections == []


def test_conditional_interest():
    result = detect("I'd sign up if I could study after work.")
    assert result.buying_signal == BuyingSignal.CONDITIONAL_INTEREST


def test_purchase_intent():
    result = detect("I'm ready to subscribe.")
    assert result.buying_signal == BuyingSignal.PURCHASE_INTENT


def test_time_objection():
    result = detect("I don't have enough time to finish this course.")
    assert Objection.TIME in result.objections


def test_price_negation_guard():
    result = detect("Actually, it's not expensive.")
    assert Objection.PRICE not in result.objections


@pytest.mark.parametrize("text", [
    "It's not expensive, but I can't afford it.",
    "I can't afford it, although it's not expensive.",
    "It's NOT TOO EXPENSIVE, but I can't afford it.",
    "It's not too expensive. Another option is too expensive, and I can't afford it.",
])
def test_price_negation_preserves_separate_affordability_concern(text):
    result = detect(text)
    assert Objection.PRICE in result.objections
    assert all(evidence in text for evidence in result.evidence)


@pytest.mark.parametrize("text", [
    "It's not too expensive.",
    "It's NOT TOO EXPENSIVE.",
    "100 dollars is not too expensive.",
])
def test_negated_expensive_phrase_is_not_price_objection(text):
    result = detect(text)
    assert Objection.PRICE not in result.objections
    assert result.evidence == []


def test_affordability_evidence_excludes_negated_expensive_phrase():
    result = detect("It's not too expensive, but I can't afford it.")
    assert result.evidence == ["can't afford"]


def test_price_detection_continues_after_negated_match():
    result = detect("The course is not too expensive, but the add-on is too expensive.")
    assert result.objections == [Objection.PRICE]
    assert result.evidence == ["too expensive"]


def test_neutral_statement():
    result = detect("My name is Alex and I work at a library.")
    assert result.buying_signal == BuyingSignal.NEUTRAL
    assert result.objections == []
