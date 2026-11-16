import asyncio

from fastapi.testclient import TestClient

from app.main import app
from app.services.conversation_access import ConversationAccessManager


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
                assert "正在对话" in second.json()["detail"]

            # The second browser leaving must not release the first owner.
            status = client.get("/api/v1/health").json()
            assert status["conversationActive"] is True

        # Closing the owner presence automatically frees the single slot.
        status = client.get("/api/v1/health").json()
        assert status["conversationActive"] is False
