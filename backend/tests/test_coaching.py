import pytest

from app.schemas import BuyingSignal, Objection, TurnInput
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
