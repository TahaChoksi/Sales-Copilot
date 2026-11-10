"""Acceptance tests for the agreed local, text-only backend MVP."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import create_app


@pytest.fixture()
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


def create_session(client, name="Synthetic software subscription"):
    response = client.post("/api/v1/sessions", json={
        "product": {"name": name, "facts": ["Lessons are recorded."]},
    })
    assert response.status_code == 201
    return response.json()["session_id"]


@pytest.mark.parametrize("turn", [
    {"speaker": "customer", "text": "Are lessons recorded?"},
    {"speaker": "customer", "text": "I'll subscribe if it integrates with our CRM."},
    {"speaker": "customer", "text": 'The demo says "I am ready to buy".'},
    {"speaker": "customer", "text": "Are lessons recorded and can I cancel?"},
    {"speaker": "customer", "text": "I like it, but it's too expensive and I'm too busy."},
    {"speaker": "customer", "text": "I'm not interested. I can't cancel."},
    {"speaker": "customer", "text": "What is the price? I'm ready to subscribe."},
    {"speaker": "salesperson", "text": "It's too expensive and I'm too busy."},
])
def test_rest_and_websocket_share_analysis_and_history_contract(client, turn):
    rest_session = create_session(client)
    ws_session = create_session(client)
    rest_response = client.post(f"/api/v1/sessions/{rest_session}/turns", json=turn)
    assert rest_response.status_code == 200
    rest = rest_response.json()
    with client.websocket_connect(f"/api/v1/sessions/{ws_session}/stream") as socket:
        socket.send_json(turn)
        event = socket.receive_json()
    assert event["type"] == "turn_processed"
    streamed = event["data"]
    assert rest.keys() == streamed.keys()
    assert rest["analysis"] == streamed["analysis"]
    assert rest["text"] == streamed["text"] == turn["text"]
    assert rest["speaker"] == streamed["speaker"] == turn["speaker"]
    for session_id, processed in [(rest_session, rest), (ws_session, streamed)]:
        history = client.get(f"/api/v1/sessions/{session_id}").json()
        assert history["turns"] == [processed]
        assert history["total_turns"] == 1
    stateless = client.post("/api/v1/analyse", json={
        **turn, "product": {"name": "Synthetic software", "facts": ["Lessons are recorded."]},
    })
    assert stateless.status_code == 200
    assert stateless.json() == rest["analysis"]


@pytest.mark.parametrize("invalid_turn", [
    {},
    {"speaker": "unknown", "text": "Hello"},
    {"speaker": "customer", "text": "   "},
    {"speaker": "customer", "text": "x" * 2001},
    {"speaker": "customer", "text": None},
    {"speaker": "customer", "text": "Hello", "unexpected": True},
])
def test_invalid_turns_do_not_mutate_session_and_stream_recovers(client, invalid_turn):
    session_id = create_session(client)
    path = f"/api/v1/sessions/{session_id}"
    assert client.post(f"{path}/turns", json=invalid_turn).status_code == 422
    with client.websocket_connect(f"{path}/stream") as socket:
        socket.send_json(invalid_turn)
        assert socket.receive_json()["code"] == "invalid_turn"
        assert client.get(path).json()["total_turns"] == 0
        socket.send_json({"speaker": "customer", "text": "Hello"})
        assert socket.receive_json()["type"] == "turn_processed"
    assert client.get(path).json()["total_turns"] == 1


def test_malformed_json_stream_recovers_without_adding_a_turn(client):
    session_id = create_session(client)
    with client.websocket_connect(f"/api/v1/sessions/{session_id}/stream") as socket:
        socket.send_text("{invalid json")
        assert socket.receive_json()["code"] == "invalid_turn"
        socket.send_json({"speaker": "customer", "text": "Hello"})
        assert socket.receive_json()["type"] == "turn_processed"
    assert client.get(f"/api/v1/sessions/{session_id}").json()["total_turns"] == 1


@pytest.mark.parametrize("product", [
    {"name": "   "},
    {"name": "x" * 121},
    {"name": "Synthetic product", "facts": [" "]},
    {"name": "Synthetic product", "facts": ["x" * 301]},
    {"name": "Synthetic product", "facts": ["Fact"] * 21},
])
def test_invalid_product_context_is_rejected(client, product):
    assert client.post("/api/v1/sessions", json={"product": product}).status_code == 422


def test_session_end_is_consistent_for_rest_and_open_or_new_streams(client):
    session_id = create_session(client)
    path = f"/api/v1/sessions/{session_id}"
    with client.websocket_connect(f"{path}/stream") as socket:
        first_end = client.post(f"{path}/end").json()
        assert client.post(f"{path}/end").json() == first_end
        turn = {"speaker": "customer", "text": "Hello"}
        assert client.post(f"{path}/turns", json=turn).status_code == 409
        socket.send_json(turn)
        with pytest.raises(WebSocketDisconnect) as caught:
            socket.receive_json()
        assert caught.value.code == 1008
    with pytest.raises(WebSocketDisconnect) as caught:
        with client.websocket_connect(f"{path}/stream"):
            pass
    assert caught.value.code == 1008
    assert client.get(path).json()["total_turns"] == 0


@pytest.mark.parametrize("suffix,payload", [
    ("/turns", {"speaker": "customer", "text": "Hello"}),
    ("/end", None),
])
def test_missing_session_mutations_return_404(client, suffix, payload):
    assert client.post(f"/api/v1/sessions/missing{suffix}", json=payload).status_code == 404


def test_product_facts_do_not_leak_between_sessions(client):
    with_facts = create_session(client)
    without_facts = client.post("/api/v1/sessions", json={
        "product": {"name": "Different synthetic software"},
    }).json()["session_id"]
    turn = {"speaker": "customer", "text": "Are lessons recorded?"}
    first = client.post(f"/api/v1/sessions/{with_facts}/turns", json=turn).json()
    second = client.post(f"/api/v1/sessions/{without_facts}/turns", json=turn).json()
    assert first["analysis"]["recommendation"]["supporting_facts"] == ["Lessons are recorded."]
    assert second["analysis"]["recommendation"] is None
