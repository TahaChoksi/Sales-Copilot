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


# Each case describes a plausible customer turn and why its expected reading
# matters. Signals describe explicit wording, never a probability of buying.
@pytest.mark.parametrize(("text", "signal", "objections", "evidence"), [
    pytest.param(
        "I like the course, but it's too expensive and I'm too busy.",
        BuyingSignal.POSITIVE_INTEREST, [Objection.PRICE, Objection.TIME],
        ["I like the course", "too expensive", "too busy"],
        id="interest-does-not-remove-budget-and-time-concerns",
    ),
    pytest.param(
        "I'm interested, but I'm not interested in subscribing now.",
        BuyingSignal.REFUSAL, [], ["I'm not interested"],
        id="explicit-refusal-takes-priority-over-general-interest",
    ),
    pytest.param(
        "I'd sign up if I could cancel, but I don't trust this.",
        BuyingSignal.CONDITIONAL_INTEREST, [Objection.TRUST, Objection.CANCELLATION],
        ["I'd sign up if", "I don't trust", "I'd sign up if I could cancel"],
        id="conditional-interest-retains-trust-and-cancellation-concerns",
    ),
    pytest.param(
        "This sounds good, but let me think about it.",
        BuyingSignal.DEFERRAL, [], ["let me think about it"],
        id="positive-reaction-with-delay-is-still-deferral",
    ),
    pytest.param(
        "What does it include? I'm ready to subscribe.",
        BuyingSignal.PURCHASE_INTENT, [], ["I'm ready to subscribe"],
        id="question-before-explicit-purchase-phrase",
    ),
    pytest.param(
        "How many hours per week? I don't have enough time.",
        BuyingSignal.INFORMATION_REQUEST, [Objection.TIME], ["don't have enough time"],
        id="question-before-time-concern-keeps-both",
    ),
    pytest.param(
        "Can I cancel? I'd sign up if I could cancel.",
        BuyingSignal.CONDITIONAL_INTEREST, [Objection.CANCELLATION],
        ["I'd sign up if", "I'd sign up if I could cancel"],
        id="question-does-not-hide-later-conditional-interest",
    ),
    pytest.param(
        "Is this a scam? It's too expensive and not a good fit.",
        BuyingSignal.INFORMATION_REQUEST,
        [Objection.PRICE, Objection.TRUST, Objection.PRODUCT_FIT],
        ["too expensive", "Is this a scam", "not a good fit"],
        id="trust-question-and-two-independent-objections",
    ),
    pytest.param(
        "What is the price? Expensive equipment is used in the lessons.",
        BuyingSignal.INFORMATION_REQUEST, [], [],
        id="isolated-topic-word-after-question-is-not-a-customer-objection",
    ),
    pytest.param(
        "The course covers time, trust, price and cancellation.",
        BuyingSignal.NEUTRAL, [], [],
        id="topic-names-alone-are-not-objections",
    ),
    pytest.param(
        "I dislike it; my colleague is interested in subscription tools.",
        BuyingSignal.NEUTRAL, [], [],
        id="partial-words-and-third-person-interest-do-not-match",
    ),
    pytest.param(
        "I’M READY TO SUBSCRIBE, but I can’t afford it.",
        BuyingSignal.PURCHASE_INTENT, [Objection.PRICE],
        ["I’M READY TO SUBSCRIBE", "can’t afford"],
        id="transcription-curly-apostrophes-and-case-preserve-original-evidence",
    ),
    pytest.param(
        "It costs $99, which is a lot.",
        BuyingSignal.NEUTRAL, [Objection.PRICE], ["$99, which is a lot"],
        id="currency-symbol-starts-a-valid-price-phrase",
    ),
    pytest.param(
        "It costs 99 dollars. Is a lot of homework included?",
        BuyingSignal.INFORMATION_REQUEST, [], [],
        id="price-pattern-must-not-join-unrelated-sentences",
    ),
    pytest.param(
        "What costs 99 dollars? A lot of material is included.",
        BuyingSignal.INFORMATION_REQUEST, [], [],
        id="price-pattern-must-not-cross-question-boundary",
    ),
    pytest.param(
        "It's not too expensive, but the upgrade is too expensive and too expensive for our team.",
        BuyingSignal.NEUTRAL, [Objection.PRICE], ["too expensive"],
        id="negation-is-local-and-repeated-objections-are-deduplicated",
    ),
])
def test_realistic_word_recognition_edge_cases(text, signal, objections, evidence):
    result = detect(text)
    assert result.buying_signal == signal
    assert result.objections == objections
    assert result.evidence == evidence
    assert all(fragment in text for fragment in result.evidence)


@pytest.mark.parametrize("text", ["", "   ", "...", "unsubscribe", "repayment"])
def test_empty_or_nonmatching_detector_input_is_neutral(text):
    # The API separately rejects blank turns; the pure detector stays safe.
    result = detect(text)
    assert result.buying_signal == BuyingSignal.NEUTRAL
    assert result.objections == []
    assert result.evidence == []


@pytest.mark.parametrize("text,signal,objections", [
    pytest.param('The demo says "I am ready to buy".', BuyingSignal.NEUTRAL, [],
                 id="quoted-demo-text-is-not-customer-intent"),
    pytest.param('The message says “I am not interested”.', BuyingSignal.NEUTRAL, [],
                 id="smart-quoted-refusal-is-not-customers-refusal"),
    pytest.param('The guide says "too expensive". I am ready to subscribe.',
                 BuyingSignal.PURCHASE_INTENT, [], id="quote-does-not-hide-independent-intent"),
    pytest.param("What if I don't want to subscribe?", BuyingSignal.INFORMATION_REQUEST, [],
                 id="hypothetical-refusal-question-is-not-refusal"),
    pytest.param("Suppose I'm ready to buy. What happens next?", BuyingSignal.INFORMATION_REQUEST, [],
                 id="hypothetical-purchase-is-not-commitment"),
    pytest.param("I'll subscribe if it integrates with our CRM.", BuyingSignal.CONDITIONAL_INTEREST, [],
                 id="future-purchase-with-condition-is-not-unconditional"),
    pytest.param("I'll buy it if the price changes.", BuyingSignal.CONDITIONAL_INTEREST, [],
                 id="object-between-purchase-and-condition"),
    pytest.param("I'm ready to subscribe if it meets our security requirements.",
                 BuyingSignal.CONDITIONAL_INTEREST, [], id="ready-to-subscribe-with-condition"),
    pytest.param("I'm not too busy, but my team is too busy.",
                 BuyingSignal.NEUTRAL, [Objection.TIME], id="local-time-negation-keeps-later-match"),
    pytest.param("I'm not too busy.", BuyingSignal.NEUTRAL, [],
                 id="negated-busy-is-not-time-objection"),
    pytest.param("It doesn't integrate with our CRM.", BuyingSignal.NEUTRAL, [Objection.PRODUCT_FIT],
                 id="explicit-software-integration-mismatch"),
    pytest.param("Does it integrate with our CRM?", BuyingSignal.INFORMATION_REQUEST, [],
                 id="software-integration-question-is-not-mismatch"),
    pytest.param("I don't have time for onboarding.", BuyingSignal.NEUTRAL, [Objection.TIME],
                 id="software-onboarding-time-constraint"),
])
def test_context_sensitive_rule_interpretation(text, signal, objections):
    result = detect(text)
    assert result.buying_signal == signal
    assert result.objections == objections
    assert all(fragment in text for fragment in result.evidence)
    if signal in (BuyingSignal.NEUTRAL, BuyingSignal.INFORMATION_REQUEST) and not objections:
        assert result.evidence == []


def test_hypothetical_cancellation_question_still_expresses_policy_concern():
    result = detect("What if I can't cancel?")
    assert result.buying_signal == BuyingSignal.INFORMATION_REQUEST
    assert result.objections == [Objection.CANCELLATION]
    assert result.evidence == ["can't cancel"]


def test_conditional_signal_and_independent_objection_keep_literal_evidence():
    result = detect("I’ll subscribe if it works, but I can’t afford it now.")
    assert result.buying_signal == BuyingSignal.CONDITIONAL_INTEREST
    assert result.objections == [Objection.PRICE]
    assert result.evidence == ["I’ll subscribe if", "can’t afford"]


def test_hypothetical_sentence_does_not_hide_later_asserted_intent():
    result = detect("Suppose I'm ready to buy. Actually, I'm ready to subscribe.")
    assert result.buying_signal == BuyingSignal.PURCHASE_INTENT
    assert result.evidence == ["I'm ready to subscribe"]


@pytest.mark.parametrize("condition", ["if", "provided that", "as long as"])
def test_explicit_subscription_conditions_are_not_purchase_intent(condition):
    text = f"I'll subscribe {condition} it meets our needs."
    result = detect(text)
    assert result.buying_signal == BuyingSignal.CONDITIONAL_INTEREST
    assert result.evidence == [f"I'll subscribe {condition}"]


def test_software_interest_and_leading_condition_have_literal_evidence():
    positive = detect("I like the software.")
    assert positive.buying_signal == BuyingSignal.POSITIVE_INTEREST
    assert positive.evidence == ["I like the software"]
    conditional = detect("If the software had audit logs, I'd subscribe.")
    assert conditional.buying_signal == BuyingSignal.CONDITIONAL_INTEREST
    assert conditional.evidence == ["If the software had audit logs, I'd subscribe"]


def test_leading_condition_does_not_span_into_separate_purchase_sentence():
    result = detect("If the course had recordings, that would help. I'd buy a different product.")
    assert result.buying_signal != BuyingSignal.CONDITIONAL_INTEREST
