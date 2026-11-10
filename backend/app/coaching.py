"""Rule-based coaching: useful as a baseline, never invents product claims."""

from __future__ import annotations

from app.detection import Detection
from app.schemas import BuyingSignal, Objection, ProductContext, Recommendation


# A deliberately narrow matching strategy. It returns product facts verbatim.
# Semantic RAG can replace this later, but unsupported product claims must not.
TOPIC_TERMS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("record", "replay", "watch later"), ("record", "replay")),
    (("price", "cost", "afford", "expensive", "monthly"), ("price", "cost", "£", "$", "monthly", "per month")),
    (("schedule", "hours", "time", "busy"), ("schedule", "hours", "self-paced", "flexible")),
    (("refund", "cancel", "cancellation"), ("refund", "cancel", "cancellation")),
)


def matching_facts(text: str, product: ProductContext | None) -> list[str]:
    if not product:
        return []
    query = text.casefold()
    for query_terms, fact_terms in TOPIC_TERMS:
        if any(term in query for term in query_terms):
            facts = [fact for fact in product.facts if any(term in fact.casefold() for term in fact_terms)]
            return facts[:2]
    return []


def recommend(text: str, detection: Detection, product: ProductContext | None) -> Recommendation | None:
    signal = detection.buying_signal
    # Respect an explicit refusal even when the same turn includes objections.
    if signal == BuyingSignal.REFUSAL:
        return None

    objections = detection.objections
    facts = matching_facts(text, product)

    # Each call returns at most one recommendation, avoiding UI spam.
    if Objection.CANCELLATION in objections:
        return Recommendation(
            action="verify_cancellation_terms",
            suggested_response="I want to give you the correct cancellation and refund terms. Let me check the official policy.",
            rationale="The customer has a cancellation/refund concern. Never invent or assume a policy.",
            supporting_facts=facts,
        )
    if Objection.TRUST in objections:
        return Recommendation(
            action="explore_credibility_concern",
            suggested_response="What would help you feel confident that this course is legitimate and suited to your goals?",
            rationale="Understand the customer's concern before presenting verifiable evidence.",
            supporting_facts=facts,
        )
    if Objection.PRICE in objections:
        return Recommendation(
            action="explore_budget",
            suggested_response="What would you need to get out of the course to feel the price is worthwhile?",
            rationale="Identify the customer's value criteria rather than immediately promising a discount.",
            supporting_facts=facts,
        )
    if Objection.TIME in objections:
        return Recommendation(
            action="clarify_time_available",
            suggested_response="How much time could you realistically set aside for learning each week?",
            rationale="Clarify the practical constraint before discussing the course format.",
            supporting_facts=facts,
        )
    if Objection.PRODUCT_FIT in objections:
        return Recommendation(
            action="clarify_requirements",
            suggested_response="What would the course need to offer to be a good fit for your goals?",
            rationale="Check the mismatch rather than claiming that the course fits every buyer.",
            supporting_facts=facts,
        )
    if signal == BuyingSignal.PURCHASE_INTENT:
        return Recommendation(
            action="clarify_next_step",
            suggested_response="Would you like me to walk through the available enrolment steps and terms?",
            rationale="The customer expressed a direct purchase intention. Confirm the next step without pressure.",
            supporting_facts=facts,
        )
    if signal == BuyingSignal.CONDITIONAL_INTEREST:
        return Recommendation(
            action="explore_condition",
            suggested_response="What specifically would need to change for this to work for you?",
            rationale="The customer has expressed interest with a condition that needs to be understood.",
            supporting_facts=facts,
        )
    if signal == BuyingSignal.DEFERRAL:
        return Recommendation(
            action="clarify_hesitation",
            suggested_response="Of course. Is there anything you're still unsure about that I can help clarify?",
            rationale="Make space for the customer's decision rather than interpreting a delay as a refusal.",
            supporting_facts=facts,
        )
    if signal == BuyingSignal.INFORMATION_REQUEST and facts:
        # Exact facts shown to the salesperson, not auto-paraphrased into claims.
        return Recommendation(
            action="answer_using_approved_fact",
            suggested_response="Use the verified product information shown below to answer, and clarify anything it doesn't cover.",
            rationale="A relevant product fact is available; use it verbatim instead of guessing.",
            supporting_facts=facts,
        )
    return None
