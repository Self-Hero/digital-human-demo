from fastapi.testclient import TestClient

from app.container import container
from app.main import app


class ShortRealtimeBridge:
    async def run(self, websocket) -> None:
        await websocket.send_json({"type": "test.complete"})


def test_realtime_websocket_removes_session_when_bridge_finishes(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.routes.sessions.create_realtime_bridge",
        lambda settings: ShortRealtimeBridge(),
    )

    with TestClient(app) as client:
        session_id = client.post("/api/v1/sessions").json()["sessionId"]
        with client.websocket_connect(
            f"/api/v1/sessions/{session_id}/realtime"
        ) as websocket:
            assert websocket.receive_json() == {"type": "test.complete"}

        assert container.sessions.get(session_id) is None
