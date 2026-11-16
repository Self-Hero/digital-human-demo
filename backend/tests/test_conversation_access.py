import asyncio

from fastapi.testclient import TestClient

from app.api.routes import access as access_routes
from app.container import container
from app.main import app
from app.services.conversation_access import ConversationAccessManager


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_only_one_client_can_acquire_conversation() -> None:
    async def scenario() -> None:
        manager = ConversationAccessManager()
        await manager.connect("client-one")
        await manager.connect("client-two")

        acquired_one, first = await manager.acquire("client-one")
        acquired_two, second = await manager.acquire("client-two")

        assert acquired_one is True
        assert first.owns_conversation is True
        assert acquired_two is False
        assert second.owns_conversation is False
        assert second.conversation_active is True
        assert second.online_clients == 2

    asyncio.run(scenario())


def test_owner_disconnect_releases_conversation() -> None:
    async def scenario() -> None:
        manager = ConversationAccessManager()
        await manager.connect("client-one")
        await manager.connect("client-two")
        assert (await manager.acquire("client-one"))[0] is True

        await manager.disconnect("client-one")
        acquired, snapshot = await manager.acquire("client-two")

        assert acquired is True
        assert snapshot.owns_conversation is True
        assert snapshot.online_clients == 1

    asyncio.run(scenario())


def test_disconnected_client_cannot_acquire() -> None:
    async def scenario() -> None:
        manager = ConversationAccessManager()
        acquired, snapshot = await manager.acquire("missing-client")

        assert acquired is False
        assert snapshot.conversation_active is False

    asyncio.run(scenario())


def test_overlapping_reconnect_does_not_release_owner() -> None:
    async def scenario() -> None:
        manager = ConversationAccessManager()
        await manager.connect("same-browser")
        assert (await manager.acquire("same-browser"))[0] is True

        await manager.connect("same-browser")
        snapshot = await manager.disconnect("same-browser")

        assert snapshot.online_clients == 1
        assert snapshot.conversation_active is True
        assert snapshot.owns_conversation is True

        snapshot = await manager.disconnect("same-browser")
        assert snapshot.online_clients == 0
        assert snapshot.conversation_active is False

    asyncio.run(scenario())


def test_inactive_conversation_can_only_be_reclaimed_after_five_minutes() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        manager = ConversationAccessManager(clock=clock)
        await manager.connect("client-owner")
        await manager.connect("client-waiting")
        assert (await manager.acquire("client-owner"))[0] is True
        await manager.bind_avatar_session("client-owner", "avatar-session")

        clock.advance(299)
        too_early = await manager.reclaim_inactive("client-waiting")
        assert too_early.reclaimed is False
        assert too_early.snapshot.conversation_reclaimable is False

        clock.advance(1)
        reclaimed = await manager.reclaim_inactive("client-waiting")
        assert reclaimed.reclaimed is True
        assert reclaimed.avatar_session_id == "avatar-session"
        assert reclaimed.snapshot.conversation_active is False

    asyncio.run(scenario())


def test_active_turn_blocks_reclaim_and_resets_idle_timer() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        manager = ConversationAccessManager(clock=clock)
        await manager.connect("client-owner")
        await manager.connect("client-waiting")
        await manager.acquire("client-owner")

        clock.advance(300)
        await manager.mark_activity("client-owner", True)
        clock.advance(600)
        active = await manager.reclaim_inactive("client-waiting")
        assert active.reclaimed is False
        assert active.snapshot.conversation_in_progress is True

        await manager.mark_activity("client-owner", False)
        clock.advance(299)
        recent = await manager.reclaim_inactive("client-waiting")
        assert recent.reclaimed is False

        clock.advance(1)
        reclaimed = await manager.reclaim_inactive("client-waiting")
        assert reclaimed.reclaimed is True

    asyncio.run(scenario())


def test_api_rejects_second_conversation_and_releases_on_disconnect() -> None:
    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/v1/access/presence/browser-one"
        ) as first_presence:
            assert first_presence.receive_json()["onlineClients"] == 1
            with client.websocket_connect(
                "/api/v1/access/presence/browser-two"
            ) as second_presence:
                assert second_presence.receive_json()["onlineClients"] == 2

                first = client.post(
                    "/api/v1/access/conversation/browser-one"
                )
                second = client.post(
                    "/api/v1/access/conversation/browser-two"
                )

                assert first.status_code == 200
                assert first.json()["ownsConversation"] is True
                assert second.status_code == 409
                assert "正在使用" in second.json()["detail"]

            # The second browser leaving must not release the first owner.
            status = client.get("/api/v1/health").json()
            assert status["conversationActive"] is True

        # Closing the owner presence automatically frees the single slot.
        status = client.get("/api/v1/health").json()
        assert status["conversationActive"] is False


def test_reclaim_api_closes_bound_livetalking_session(monkeypatch) -> None:
    deleted_urls: list[str] = []

    class FakeResponse:
        status_code = 200

    class FakeAsyncClient:
        def __init__(self, *, timeout: float) -> None:
            assert timeout == 3.0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def delete(self, url: str) -> FakeResponse:
            deleted_urls.append(url)
            return FakeResponse()

    monkeypatch.setattr(access_routes.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(container.access, "_inactive_timeout_seconds", 0)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/v1/access/presence/browser-owner"
        ) as owner_presence:
            owner_presence.receive_json()
            with client.websocket_connect(
                "/api/v1/access/presence/browser-waiting"
            ) as waiting_presence:
                waiting_presence.receive_json()
                assert client.post(
                    "/api/v1/access/conversation/browser-owner"
                ).status_code == 200
                assert client.put(
                    "/api/v1/access/conversation/browser-owner/avatar/avatar-session"
                ).status_code == 200

                reclaimed = client.post(
                    "/api/v1/access/conversation/browser-waiting/reclaim"
                )

                assert reclaimed.status_code == 200
                assert reclaimed.json()["conversationActive"] is False

    assert deleted_urls == ["http://127.0.0.1:8010/session/avatar-session"]
