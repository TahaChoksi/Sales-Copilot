import pytest

from app.coaching import matching_facts
from app.schemas import BuyingSignal, Objection, ProductContext, TurnInput
from app.store import analyse_turn


@pytest.mark.parametrize(
    ("concern", "objection"),
    [
        ("It's too expensive.", Objection.PRICE),
        ("I'm too busy.", Objection.TIME),
        ("I don't trust this.", Objection.TRUST),
        ("It's not a good fit.", Objection.PRODUCT_FIT),
        ("I'm worried about the refund policy.", Objection.CANCELLATION),
    ],
)
def test_refusal_suppresses_coaching_but_preserves_objections_and_evidence(concern, objection):
    concern_result = analyse_turn(TurnInput(speaker="customer", text=concern))
    assert concern_result.recommendation is not None
    assert objection in concern_result.objections

    result = analyse_turn(TurnInput(speaker="customer", text=f"I'm not interested. {concern}"))

    assert result.buying_signal == BuyingSignal.REFUSAL
    assert result.objections == concern_result.objections
    assert "I'm not interested" in result.evidence
    assert all(evidence in result.evidence for evidence in concern_result.evidence)
    assert result.recommendation is None


def test_plain_refusal_has_no_recommendation():
    result = analyse_turn(TurnInput(speaker="customer", text="I don't want to subscribe."))

    assert result.buying_signal == BuyingSignal.REFUSAL
    assert result.objections == []
    assert result.recommendation is None


def test_deferral_still_receives_coaching():
    result = analyse_turn(TurnInput(speaker="customer", text="Let me think about it."))

    assert result.buying_signal == BuyingSignal.DEFERRAL
    assert result.recommendation is not None
    assert result.recommendation.action == "clarify_hesitation"


def test_multitopic_question_surfaces_one_fact_per_topic():
    product = ProductContext(name="Synthetic software", facts=[
        "The price is $20 monthly.", "The annual price is $200.",
        "You can cancel from account settings.",
    ])
    assert matching_facts("What is the price and can I cancel?", product) == [
        "The price is $20 monthly.", "You can cancel from account settings.",
    ]


def test_missing_first_topic_does_not_hide_other_facts():
    product = ProductContext(name="Synthetic course", facts=["The price is $20 monthly."])
    assert matching_facts("Are lessons recorded and what is the price?", product) == product.facts


def test_fact_matching_respects_words_and_deduplicates_facts():
    product = ProductContext(name="Synthetic product", facts=[
        "A costume guide is included.", "The price is $20 monthly; cancel in settings.",
        "The price is $20 monthly; cancel in settings.",
    ])
    assert matching_facts("What does it cost and can I cancel?", product) == [product.facts[1]]
    assert matching_facts("Our costume archive is large.", product) == []
    assert matching_facts("What does it cost?", ProductContext(
        name="Synthetic product", facts=["A costume guide is included."],
    )) == []


def test_selected_objection_gets_relevant_facts_in_multitopic_turn():
    product = ProductContext(name="Synthetic software", facts=[
        "Lessons are recorded.", "The price is $20 monthly.",
        "You can cancel from account settings.",
    ])
    result = analyse_turn(TurnInput(speaker="customer", text=(
        "Are lessons recorded? It's too expensive and I'm worried about the cancellation policy."
    )), product)
    assert result.recommendation.action == "verify_cancellation_terms"
    assert result.recommendation.supporting_facts == [product.facts[2]]


def test_no_unrelated_facts_for_selected_objection():
    product = ProductContext(name="Synthetic software", facts=["The price is $20 monthly."])
    result = analyse_turn(TurnInput(speaker="customer", text=(
        "What is the price? I don't trust this."
    )), product)
    assert result.recommendation.action == "explore_credibility_concern"
    assert result.recommendation.supporting_facts == []


def test_software_integration_question_uses_only_supplied_fact():
    product = ProductContext(name="Synthetic software", facts=["Integrates with Example CRM."])
    result = analyse_turn(TurnInput(speaker="customer", text="Which integrations are supported?"), product)
    assert result.recommendation.action == "answer_using_approved_fact"
    assert result.recommendation.supporting_facts == product.facts
    assert "verified" not in result.recommendation.suggested_response.lower()


@pytest.mark.parametrize("text,action", [
    ("I don't trust this.", "explore_credibility_concern"),
    ("It's too expensive.", "explore_budget"),
    ("I don't have time for onboarding.", "clarify_time_available"),
    ("It doesn't integrate with our CRM.", "clarify_requirements"),
    ("I'm ready to subscribe.", "clarify_next_step"),
])
def test_coaching_supports_software_without_assuming_course_features(text, action):
    result = analyse_turn(TurnInput(speaker="customer", text=text), ProductContext(name="Synthetic software"))
    assert result.recommendation.action == action
    response = result.recommendation.suggested_response.lower()
    assert all(word not in response for word in ["course", "learning", "enrolment", "lessons"])
    assert result.recommendation.supporting_facts == []


def test_retrieval_returns_second_fact_when_only_one_topic_is_mentioned():
    product = ProductContext(name="Synthetic software", facts=[
        "The price is $20 monthly.", "The annual price is $200.", "Refunds are not offered.",
    ])
    assert matching_facts("What is the price?", product) == product.facts[:2]
    assert matching_facts("What is the price?", None) == []


def test_security_concern_and_integration_mismatch_get_relevant_software_facts():
    product = ProductContext(name="Synthetic software", facts=[
        "The price is $20 monthly.", "Data encryption is enabled.", "Integrates with Example CRM.",
    ])
    trust = analyse_turn(TurnInput(
        speaker="customer", text="What is the price? I don't trust its data security.",
    ), product)
    assert trust.recommendation.supporting_facts == [product.facts[1]]
    fit = analyse_turn(TurnInput(
        speaker="customer", text="It doesn't integrate with our CRM.",
    ), product)
    assert fit.recommendation.supporting_facts == [product.facts[2]]
