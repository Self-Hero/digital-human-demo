from fastapi.testclient import TestClient

from app.main import app


def test_health_reports_mock_providers() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["providers"]["avatar"] == "mock"


def test_session_lifecycle() -> None:
    with TestClient(app) as client:
        created = client.post("/api/v1/sessions")
        assert created.status_code == 201
        session_id = created.json()["sessionId"]

        deleted = client.delete(f"/api/v1/sessions/{session_id}")
        assert deleted.status_code == 204


def test_mock_conversation_stream() -> None:
    with TestClient(app) as client:
        session_id = client.post("/api/v1/sessions").json()["sessionId"]

        with client.websocket_connect(f"/api/v1/sessions/{session_id}/events") as websocket:
            assert websocket.receive_json()["type"] == "session.ready"
            assert websocket.receive_json() == {"type": "session.state", "state": "idle"}

            websocket.send_json({"type": "user.text", "text": "你好"})
            received_types: list[str] = []
            while "turn.completed" not in received_types:
                received_types.append(websocket.receive_json()["type"])

        assert "transcript.user" in received_types
        assert "assistant.delta" in received_types
        assert "audio.chunk" in received_types
