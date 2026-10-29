from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app


def test_health_reports_mock_providers() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["providers"]["realtime"] == "doubao"
    assert payload["providers"]["avatar"] == "mock"


def test_bailian_realtime_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.bailian_base_url.endswith("/compatible-mode/v1")
    assert settings.bailian_realtime_url == (
        "wss://token-plan.maas.qianwenaiapi.com/api-ws/v1/realtime"
    )
    assert settings.bailian_realtime_model == "qwen-audio-3.0-realtime-plus"
    assert settings.bailian_realtime_voice == "longanqian"


def test_doubao_legacy_realtime_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.realtime_provider == "doubao"
    assert settings.doubao_realtime_url == (
        "wss://openspeech.bytedance.com/api/v3/realtime/dialogue"
    )
    assert settings.doubao_resource_id == "volc.speech.dialog"
    assert settings.doubao_app_key == "PlgvMymc7f3tQnJ6"
    assert settings.doubao_recv_timeout == 120


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
