import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture()
def client():
    return TestClient(create_app())


@pytest.fixture()
def created_session(client):
    response = client.post("/api/v1/sessions", json={
        "product": {"name": "Demo Python Course", "facts": ["All lessons are recorded."]}
    })
    assert response.status_code == 201
    return response.json()["session_id"]


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_stateless_analysis_customer(client):
    response = client.post("/api/v1/analyse", json={
        "speaker": "customer", "text": "I like the course but it is too expensive."
    })
    assert response.status_code == 200
    assert response.json()["objections"] == ["price"]
    assert response.json()["recommendation"]["action"] == "explore_budget"


def test_stateless_salesperson_does_not_trigger_coaching(client):
    response = client.post("/api/v1/analyse", json={
        "speaker": "salesperson", "text": "It's too expensive for you?"
    })
    assert response.status_code == 200
    assert response.json()["recommendation"] is None
    assert response.json()["objections"] == []


def test_session_turn_and_history(client, created_session):
    result = client.post(f"/api/v1/sessions/{created_session}/turns", json={
        "speaker": "customer", "text": "Are lessons recorded?"
    })
    assert result.status_code == 200
    analysis = result.json()["analysis"]
    assert analysis["buying_signal"] == "information_request"
    assert analysis["recommendation"]["supporting_facts"] == ["All lessons are recorded."]
    history = client.get(f"/api/v1/sessions/{created_session}")
    assert history.status_code == 200
    assert history.json()["total_turns"] == 1
    assert len(history.json()["turns"]) == 1
    assert history.json()["state"]["last_customer_message"] == "Are lessons recorded?"


def test_ending_session_blocks_new_turns(client, created_session):
    ended = client.post(f"/api/v1/sessions/{created_session}/end")
    assert ended.status_code == 200
    assert ended.json()["status"] == "ended"
    new_turn = client.post(f"/api/v1/sessions/{created_session}/turns", json={
        "speaker": "customer", "text": "Ready to subscribe"
    })
    assert new_turn.status_code == 409


def test_nonexistent_session_returns_404(client):
    assert client.get("/api/v1/sessions/does-not-exist").status_code == 404


def test_blank_turn_is_rejected(client, created_session):
    response = client.post(f"/api/v1/sessions/{created_session}/turns", json={
        "speaker": "customer", "text": "   "
    })
    assert response.status_code == 422


def test_extra_fields_rejected(client):
    response = client.post("/api/v1/analyse", json={
        "speaker": "customer", "text": "Hello", "secret_attribute": "unexpected"
    })
    assert response.status_code == 422


def test_conversation_state_tracks_objections_not_implied_resolution(client, created_session):
    for speaker, message in [
        ("customer", "I am too busy to study."),
        ("salesperson", "The lessons are recorded."),
        ("customer", "It's too expensive."),
    ]:
        response = client.post(f"/api/v1/sessions/{created_session}/turns", json={
            "speaker": speaker, "text": message
        })
        assert response.status_code == 200
    state = client.get(f"/api/v1/sessions/{created_session}").json()["state"]
    assert state["last_salesperson_message"] == "The lessons are recorded."
    assert state["observed_objections"] == ["time_commitment", "price"]
    assert state["last_customer_message"] == "It's too expensive."
