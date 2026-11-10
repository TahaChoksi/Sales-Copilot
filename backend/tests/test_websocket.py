from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
import pytest

from app.main import create_app


def test_websocket_stream_returns_processed_turn():
    client = TestClient(create_app())
    session = client.post("/api/v1/sessions", json={
        "product": {"name": "Example monthly course"}
    }).json()
    with client.websocket_connect(f"/api/v1/sessions/{session['session_id']}/stream") as socket:
        socket.send_json({"speaker": "customer", "text": "I don't have enough time."})
        event = socket.receive_json()
        assert event["type"] == "turn_processed"
        assert event["data"]["analysis"]["objections"] == ["time_commitment"]


def test_invalid_websocket_payload_reports_error_and_recovers():
    client = TestClient(create_app())
    session = client.post("/api/v1/sessions", json={
        "product": {"name": "Example monthly course"}
    }).json()
    with client.websocket_connect(f"/api/v1/sessions/{session['session_id']}/stream") as socket:
        socket.send_json({"speaker": "customer", "text": ""})
        error = socket.receive_json()
        assert error["type"] == "error"
        assert error["code"] == "invalid_turn"
        socket.send_json({"speaker": "customer", "text": "How much does it cost?"})
        assert socket.receive_json()["type"] == "turn_processed"


def test_nonexistent_session_websocket_closes():
    client = TestClient(create_app())
    with pytest.raises(WebSocketDisconnect) as caught:
        with client.websocket_connect("/api/v1/sessions/no-session/stream"):
            pass
    assert caught.value.code == 1008
