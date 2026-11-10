"""API contracts. These are independent of how events arrive (REST, WS, audio later)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Speaker(str, Enum):
    CUSTOMER = "customer"
    SALESPERSON = "salesperson"


class BuyingSignal(str, Enum):
    PURCHASE_INTENT = "purchase_intent"
    CONDITIONAL_INTEREST = "conditional_interest"
    POSITIVE_INTEREST = "positive_interest"
    INFORMATION_REQUEST = "information_request"
    DEFERRAL = "deferral"
    REFUSAL = "refusal"
    NEUTRAL = "neutral"


class Objection(str, Enum):
    PRICE = "price"
    TIME = "time_commitment"
    TRUST = "trust"
    PRODUCT_FIT = "product_fit"
    CANCELLATION = "cancellation_or_refund"


class ProductContext(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    facts: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Product name cannot be blank")
        return value.strip()

    @field_validator("facts")
    @classmethod
    def validate_facts(cls, facts: list[str]) -> list[str]:
        if any(not fact.strip() or len(fact) > 300 for fact in facts):
            raise ValueError("Each product fact must be 1–300 non-whitespace characters")
        return [fact.strip() for fact in facts]


class CreateSession(StrictModel):
    product: ProductContext


class TurnInput(StrictModel):
    speaker: Speaker
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Transcript text cannot be blank")
        return value.strip()


class AnalyseInput(TurnInput):
    product: ProductContext | None = None


class Recommendation(StrictModel):
    action: str
    suggested_response: str
    rationale: str
    supporting_facts: list[str] = Field(default_factory=list)


class AnalysisResult(StrictModel):
    buying_signal: BuyingSignal
    objections: list[Objection]
    evidence: list[str]
    recommendation: Recommendation | None = None
    engine: Literal["rules-v0.1"] = "rules-v0.1"


class ProcessedTurn(StrictModel):
    turn_id: str
    speaker: Speaker
    text: str
    received_at: datetime
    analysis: AnalysisResult


class ConversationState(StrictModel):
    last_customer_message: str | None = None
    last_salesperson_message: str | None = None
    last_customer_signal: BuyingSignal | None = None
    observed_objections: list[Objection] = Field(default_factory=list)


class SessionView(StrictModel):
    session_id: str
    status: Literal["active", "ended"]
    created_at: datetime
    ended_at: datetime | None = None
    product: ProductContext
    state: ConversationState
    total_turns: int
    turns: list[ProcessedTurn]


class ErrorEvent(StrictModel):
    type: Literal["error"] = "error"
    code: str
    message: str
