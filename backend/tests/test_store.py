"""Session lifecycle and isolation checks using synthetic conversations."""

import pytest

from app.schemas import CreateSession, TurnInput
from app.store import ClosedSession, MissingSession, SessionStore


def test_store_owns_product_facts_and_returns_independent_snapshots():
    store = SessionStore()
    request = CreateSession(product={"name": "Synthetic software", "facts": ["Costs $20 monthly."]})
    created = store.create(request)
    request.product.facts.append("Unapproved request mutation")
    created.product.facts.append("Unapproved response mutation")

    turn = store.add_turn(created.session_id, TurnInput(speaker="customer", text="It's too expensive."))
    turn.text = "Changed externally"
    turn.analysis.objections.clear()
    turn.analysis.recommendation.supporting_facts.append("Unapproved recommendation mutation")

    snapshot = store.read(created.session_id)
    assert snapshot.product.facts == ["Costs $20 monthly."]
    assert snapshot.turns[0].text == "It's too expensive."
    assert snapshot.state.observed_objections == ["price"]
    assert snapshot.turns[0].analysis.recommendation.supporting_facts == ["Costs $20 monthly."]
    snapshot.turns.clear()
    snapshot.product.facts.clear()
    snapshot.state.observed_objections.clear()
    assert store.read(created.session_id).total_turns == 1
    assert store.read(created.session_id).product.facts == ["Costs $20 monthly."]


def test_sessions_and_store_instances_are_isolated():
    store = SessionStore()
    first = store.create(CreateSession(product={"name": "First product"}))
    second = store.create(CreateSession(product={"name": "Second product"}))
    store.add_turn(first.session_id, TurnInput(speaker="customer", text="I'm too busy."))
    assert store.read(second.session_id).turns == []
    assert store.read(second.session_id).state.observed_objections == []
    with pytest.raises(MissingSession):
        SessionStore().read(first.session_id)


def test_end_is_idempotent_and_ended_snapshot_cannot_mutate_history():
    store = SessionStore()
    session = store.create(CreateSession(product={"name": "Synthetic course"}))
    store.add_turn(session.session_id, TurnInput(speaker="customer", text="Hello"))
    ended = store.end(session.session_id)
    assert ended.ended_at is not None
    assert store.end(session.session_id).ended_at == ended.ended_at
    ended.turns[0].text = "Changed externally"
    assert store.read(session.session_id).turns[0].text == "Hello"
    with pytest.raises(ClosedSession):
        store.add_turn(session.session_id, TurnInput(speaker="customer", text="Hello again"))
    assert store.read(session.session_id).total_turns == 1


@pytest.mark.parametrize("operation", ["read", "add_turn", "end"])
def test_missing_session_operations(operation):
    store = SessionStore()
    args = ["missing"]
    if operation == "add_turn":
        args.append(TurnInput(speaker="customer", text="Hello"))
    with pytest.raises(MissingSession):
        getattr(store, operation)(*args)
