"""Rule-based coaching: useful as a baseline, never invents product claims."""

from __future__ import annotations

import re

from app.detection import Detection
from app.schemas import BuyingSignal, Objection, ProductContext, Recommendation


# Explicit word forms avoid substring matches such as "cost" in "costume".
# These patterns locate supplied facts; they do not verify their truth.
TOPIC_TERMS: dict[str, str] = {
    "recording": r"\b(?:record(?:ed|ing|ings)?|replay(?:s|ed)?|watch later)\b",
    "price": r"\b(?:price|prices|pricing|cost|costs|afford|expensive|monthly|per month|budget)\b|[£$]",
    "time": r"\b(?:schedule|hours?|time|busy|self-paced|flexible|onboarding|setup|implementation)\b",
    "cancellation": r"\b(?:refunds?|cancel(?:led|ed|lation|lations|ling|ing)?|termination)\b",
    "integration": r"\b(?:integrat(?:e|es|ed|ion|ions)|compatib(?:le|ility)|crm)\b",
    "security": r"\b(?:security|privacy|encrypt(?:ed|ion)|data protection)\b",
}

OBJECTION_TOPICS: dict[Objection, tuple[str, ...]] = {
    Objection.PRICE: ("price",),
    Objection.TIME: ("time",),
    Objection.CANCELLATION: ("cancellation",),
    # Trust/fit can mean many things. Require an explicit matching topic rather
    # than attaching pricing facts to credibility or compatibility advice.
    Objection.TRUST: ("security",),
    Objection.PRODUCT_FIT: ("integration",),
}


def matching_facts(
    text: str,
    product: ProductContext | None,
    *,
    topics: tuple[str, ...] | None = None,
) -> list[str]:
    if not product:
        return []
    mentioned = [
        topic for topic, pattern in TOPIC_TERMS.items()
        if re.search(pattern, text, re.IGNORECASE)
        and (topics is None or topic in topics)
    ]
    candidates = [
        [fact for fact in product.facts if re.search(TOPIC_TERMS[topic], fact, re.IGNORECASE)]
        for topic in mentioned
    ]
    # Round-robin gives each topic a chance before a second fact from one topic.
    # Preserve supplied wording and stable order, with a two-fact UI limit.
    facts: list[str] = []
    for index in range(len(product.facts)):
        for group in candidates:
            if index < len(group) and group[index] not in facts:
                facts.append(group[index])
                if len(facts) == 2:
                    return facts
    return facts


def recommend(text: str, detection: Detection, product: ProductContext | None) -> Recommendation | None:
    signal = detection.buying_signal
    # Respect an explicit refusal even when the same turn includes objections.
    if signal == BuyingSignal.REFUSAL:
        return None

    objections = detection.objections
    selected_objection = next((objection for objection in (
        Objection.CANCELLATION, Objection.TRUST, Objection.PRICE,
        Objection.TIME, Objection.PRODUCT_FIT,
    ) if objection in objections), None)
    facts = matching_facts(
        text, product,
        topics=OBJECTION_TOPICS[selected_objection] if selected_objection else None,
    )

    # Each call returns at most one recommendation, avoiding UI spam.
    if selected_objection == Objection.CANCELLATION:
        return Recommendation(
            action="verify_cancellation_terms",
            suggested_response="I want to give you the correct cancellation and refund terms. Let me check the official policy.",
            rationale="The customer has a cancellation/refund concern. Never invent or assume a policy.",
            supporting_facts=facts,
        )
    if selected_objection == Objection.TRUST:
        return Recommendation(
            action="explore_credibility_concern",
            suggested_response="What would help you feel confident that this product is legitimate and suited to your goals?",
            rationale="Understand the customer's concern before presenting verifiable evidence.",
            supporting_facts=facts,
        )
    if selected_objection == Objection.PRICE:
        return Recommendation(
            action="explore_budget",
            suggested_response="What would you need to get out of the product to feel the price is worthwhile?",
            rationale="Identify the customer's value criteria rather than immediately promising a discount.",
            supporting_facts=facts,
        )
    if selected_objection == Objection.TIME:
        return Recommendation(
            action="clarify_time_available",
            suggested_response="What time constraints would affect getting started and using the product?",
            rationale="Clarify the practical constraint before discussing setup or ongoing use.",
            supporting_facts=facts,
        )
    if selected_objection == Objection.PRODUCT_FIT:
        return Recommendation(
            action="clarify_requirements",
            suggested_response="What would the product need to offer to be a good fit for your goals?",
            rationale="Check the mismatch rather than claiming that the product fits every buyer.",
            supporting_facts=facts,
        )
    if signal == BuyingSignal.PURCHASE_INTENT:
        return Recommendation(
            action="clarify_next_step",
            suggested_response="Would you like me to walk through the available sign-up steps and terms?",
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
            suggested_response="Use the supplied product information shown below to answer, and clarify anything it doesn't cover.",
            rationale="Relevant supplied product information is available; use it verbatim instead of guessing.",
            supporting_facts=facts,
        )
    return None
