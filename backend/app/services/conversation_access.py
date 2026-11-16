import asyncio
from dataclasses import dataclass


@dataclass(frozen=True)
class AccessSnapshot:
    online_clients: int
    conversation_active: bool
    owns_conversation: bool


class ConversationAccessManager:
    """Track online pages and grant one exclusive LiveTalking conversation."""

    def __init__(self) -> None:
        self._client_connections: dict[str, int] = {}
        self._owner_id: str | None = None
        self._lock = asyncio.Lock()

    async def connect(self, client_id: str) -> AccessSnapshot:
        async with self._lock:
            self._client_connections[client_id] = (
                self._client_connections.get(client_id, 0) + 1
            )
            return self._snapshot(client_id)

    async def disconnect(self, client_id: str) -> AccessSnapshot:
        async with self._lock:
            remaining = self._client_connections.get(client_id, 0) - 1
            if remaining > 0:
                self._client_connections[client_id] = remaining
            else:
                self._client_connections.pop(client_id, None)
                if self._owner_id == client_id:
                    self._owner_id = None
            return self._snapshot(client_id)

    async def acquire(self, client_id: str) -> tuple[bool, AccessSnapshot]:
        async with self._lock:
            if client_id not in self._client_connections:
                return False, self._snapshot(client_id)
            acquired = self._owner_id in (None, client_id)
            if acquired:
                self._owner_id = client_id
            return acquired, self._snapshot(client_id)

    async def release(self, client_id: str) -> AccessSnapshot:
        async with self._lock:
            if self._owner_id == client_id:
                self._owner_id = None
            return self._snapshot(client_id)

    async def snapshot(self, client_id: str | None = None) -> AccessSnapshot:
        async with self._lock:
            return self._snapshot(client_id)

    def _snapshot(self, client_id: str | None) -> AccessSnapshot:
        return AccessSnapshot(
            online_clients=len(self._client_connections),
            conversation_active=self._owner_id is not None,
            owns_conversation=self._owner_id == client_id,
        )
