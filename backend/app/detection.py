"""Deterministic, intentionally limited sales-signal baseline.

Do not treat these heuristics as trained probabilities, validated psychology, or
real-world purchase predictions. Future ML models should implement the same
analyse() interface and be compared on held-out conversations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas import BuyingSignal, Objection


@dataclass(frozen=True)
class Detection:
    buying_signal: BuyingSignal
    objections: list[Objection]
    evidence: list[str]


SIGNAL_PATTERNS: list[tuple[BuyingSignal, tuple[str, ...]]] = [
    (BuyingSignal.REFUSAL, (
        r"\b(?:i(?:\s+am|'m) not interested|i (?:don't|do not) want to (?:buy|enrol|enroll|subscribe|sign up)|i (?:won't|will not) (?:buy|enrol|enroll|subscribe|sign up)|no thanks[,.]? i(?:\s+am|'m) not interested)\b",
    )),
    (BuyingSignal.CONDITIONAL_INTEREST, (
        r"\bi(?:'ll| will| am ready to|'m ready to) (?:sign up|buy|subscribe|enrol|enroll)(?: it)? (?:if|provided that|as long as)\b",
        r"\b(?:i(?:\s+would|'d|\s+could)\s+(?:sign up|enrol|enroll|buy|subscribe|be interested)\s+if)\b",
        r"\bif (?:you|it|the course|the software|the product) (?:had|offered|included)\b[^.!?;\n]{0,80}\b(?:i(?:\s+would|'d) (?:sign up|buy|join|enrol|subscribe))\b",
    )),
    (BuyingSignal.PURCHASE_INTENT, (
        r"\b(?:where (?:can|do) i (?:pay|sign up|enrol|enroll|subscribe)|i(?:\s+am|'m) ready to (?:buy|enrol|enroll|subscribe|sign up)|i(?:\s+will|'ll) (?:sign up|buy|subscribe|enrol|enroll)|send me (?:the |a )?(?:payment|checkout) link)\b",
    )),
    (BuyingSignal.DEFERRAL, (
        r"\b(?:let me think about it|i (?:need|want) to think about it|not sure yet|maybe later|i(?:\s+will|'ll) get back to you|need to talk (?:it over )?with my partner)\b",
    )),
    (BuyingSignal.POSITIVE_INTEREST, (
        r"\b(?:i (?:really )?like (?:it|the course|the software|the product|the idea|this)|i(?:\s+am|'m) interested|(?:it|this|that) sounds (?:great|good|useful|interesting)|(?:it|this|that) looks (?:great|good|useful|interesting))\b",
    )),
]

OBJECTION_PATTERNS: list[tuple[Objection, tuple[str, ...]]] = [
    (Objection.PRICE, (
        r"\b(?:too expensive|(?:seems|looks|is|feels) expensive|can't afford|cannot afford|out of (?:my|our) budget|price is (?:too )?high|costs too much)\b",
        r"(?:\b\d+\s*(?:pounds|dollars)\b|(?<!\w)[£$]\s*\d+\b)[^.!?;\n]{0,35}\b(?:expensive|a lot|too much)\b",
    )),
    (Objection.TIME, (
        r"\b(?:don't have (?:enough )?time|do not have (?:enough )?time|not enough time|too busy|can't find the time|cannot find the time|can't fit (?:it|this) in|won't have (?:enough )?time|worried about (?:the )?time commitment|not sure (?:i|we)(?:'ll| will) have time)\b",
    )),
    (Objection.TRUST, (
        r"\b(?:is this a scam|this seems like a scam|i (?:don't|do not) trust|how (?:do|can) i know (?:this|it) (?:is legit|works)|sounds too good to be true|i(?:'m| am) concerned (?:this|it) (?:isn't|is not) legitimate)\b",
    )),
    (Objection.PRODUCT_FIT, (
        r"\b(?:it|this|the software) (?:doesn't|does not) (?:integrate|work) with (?:my|our)\b",
        r"\b(?:not right for me|not a good fit|doesn't (?:fit|match) (?:my|our) (?:needs|goals)|too advanced for me|too basic for me|not what i(?:'m| am) looking for)\b",
    )),
    (Objection.CANCELLATION, (
        r"\b(?:can't cancel|cannot cancel|no refund|no refunds|no cancellation|won't be able to cancel|worried about (?:the )?(?:refund|cancellation) policy|i(?:'d| would) (?:sign up|subscribe) if i could cancel)\b",
    )),
]


def _first_match(
    text: str,
    patterns: tuple[str, ...],
    ignored_spans: tuple[tuple[int, int], ...] = (),
) -> str | None:
    # One-character substitutions preserve offsets into the original transcript.
    # Return original wording as evidence, including its punctuation and case.
    searchable = text.translate(str.maketrans({"’": "'", "‘": "'"}))
    for pattern in patterns:
        for match in re.finditer(pattern, searchable, flags=re.IGNORECASE):
            if any(match.start() < end and match.end() > start for start, end in ignored_spans):
                continue
            return text[match.start():match.end()]
    return None


def _quoted_spans(text: str) -> tuple[tuple[int, int], ...]:
    """Conservatively ignore explicit quotations.

    This is intentionally not a general reported-speech or negation parser.
    Apostrophes in contractions are not quotation boundaries.
    """
    return tuple(match.span() for match in re.finditer(
        r'"[^"\n]*"|“[^”\n]*”',
        text, re.IGNORECASE,
    ))


def detect(text: str) -> Detection:
    evidence: list[str] = []
    objections: list[Objection] = []
    nonasserted_spans = _quoted_spans(text)
    # A hypothetical commitment is not an actual commitment. Hypothetical
    # policy questions can still express a concern ("What if I can't cancel?").
    hypothetical_spans = tuple(match.span() for match in re.finditer(
        r"(?:^|[.!?;\n])\s*(?:what if|suppose|imagine)\b[^.!?;\n]*",
        text, re.IGNORECASE,
    ))
    negated_price_spans = tuple(
        match.span()
        for match in re.finditer(r"\bnot\s+(?:too\s+)?expensive\b", text, re.IGNORECASE)
    )

    negated_time_spans = tuple(
        match.span() for match in re.finditer(r"\bnot\s+too\s+busy\b", text, re.IGNORECASE)
    )
    for objection, patterns in OBJECTION_PATTERNS:
        # Ignore only matches overlapping the negated phrase, then keep looking
        # for separate concerns in the same customer turn.
        ignored = nonasserted_spans
        if objection == Objection.PRICE:
            ignored += negated_price_spans
        elif objection == Objection.TIME:
            ignored += negated_time_spans
        match = _first_match(text, patterns, ignored)
        if match:
            objections.append(objection)
            evidence.append(match)

    for signal, patterns in SIGNAL_PATTERNS:
        match = _first_match(text, patterns, nonasserted_spans + hypothetical_spans)
        if match:
            evidence.insert(0, match)
            return Detection(signal, objections, list(dict.fromkeys(evidence)))

    if "?" in text or re.match(r"^\s*(?:how|what|when|where|can|could|does|do|is|are|will|would)\b", text, re.IGNORECASE):
        return Detection(BuyingSignal.INFORMATION_REQUEST, objections, evidence)

    return Detection(BuyingSignal.NEUTRAL, objections, evidence)
