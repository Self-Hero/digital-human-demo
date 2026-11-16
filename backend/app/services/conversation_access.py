import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass


DEFAULT_INACTIVE_TIMEOUT_SECONDS = 5 * 60
DEFAULT_DISCONNECT_GRACE_SECONDS = 5.0


@dataclass(frozen=True)
class AccessSnapshot:
    online_clients: int
    conversation_active: bool
    conversation_in_progress: bool
    owns_conversation: bool


@dataclass(frozen=True)
class ReclaimResult:
    reclaimed: bool
    snapshot: AccessSnapshot
    avatar_session_id: str | None = None
    reason: str | None = None


class ConversationAccessManager:
    """Track online pages and grant one exclusive LiveTalking conversation."""

    def __init__(
        self,
        *,
        inactive_timeout_seconds: float = DEFAULT_INACTIVE_TIMEOUT_SECONDS,
        disconnect_grace_seconds: float = DEFAULT_DISCONNECT_GRACE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client_connections: dict[str, int] = {}
        self._owner_id: str | None = None
        self._owner_avatar_session_id: str | None = None
        self._conversation_in_progress = False
        self._last_activity_at: float | None = None
        self._inactive_timeout_seconds = inactive_timeout_seconds
        self._disconnect_grace_seconds = disconnect_grace_seconds
        self._clock = clock
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
                return self._snapshot(client_id)

            self._client_connections.pop(client_id, None)
            should_delay_release = (
                self._owner_id == client_id
                and self._disconnect_grace_seconds > 0
            )
            if not should_delay_release:
                if self._owner_id == client_id:
                    self._clear_owner()
                return self._snapshot(client_id)

        await asyncio.sleep(self._disconnect_grace_seconds)
        async with self._lock:
            if (
                client_id not in self._client_connections
                and self._owner_id == client_id
            ):
                self._clear_owner()
            return self._snapshot(client_id)

    async def acquire(self, client_id: str) -> tuple[bool, AccessSnapshot]:
        async with self._lock:
            if client_id not in self._client_connections:
                return False, self._snapshot(client_id)
            acquired = self._owner_id in (None, client_id)
            if self._owner_id is None and acquired:
                self._owner_id = client_id
                self._last_activity_at = self._clock()
            return acquired, self._snapshot(client_id)

    async def release(self, client_id: str) -> AccessSnapshot:
        async with self._lock:
            if self._owner_id == client_id:
                self._clear_owner()
            return self._snapshot(client_id)

    async def bind_avatar_session(
        self, client_id: str, avatar_session_id: str
    ) -> AccessSnapshot:
        async with self._lock:
            if self._owner_id == client_id:
                self._owner_avatar_session_id = avatar_session_id
            return self._snapshot(client_id)

    async def mark_activity(
        self, client_id: str, active: bool
    ) -> AccessSnapshot:
        async with self._lock:
            if self._owner_id != client_id:
                return self._snapshot(client_id)

            now = self._clock()
            if active:
                self._conversation_in_progress = True
                self._last_activity_at = now
            elif self._conversation_in_progress:
                self._conversation_in_progress = False
                self._last_activity_at = now
            return self._snapshot(client_id)

    async def reclaim_inactive(self, client_id: str) -> ReclaimResult:
        async with self._lock:
            now = self._clock()
            snapshot = self._snapshot(client_id)
            if client_id not in self._client_connections:
                return ReclaimResult(False, snapshot, reason="页面连接已失效")
            if self._owner_id is None:
                return ReclaimResult(False, snapshot, reason="当前没有占用会话")
            if self._owner_id == client_id:
                return ReclaimResult(False, snapshot, reason="不能释放当前页面的会话")
            if self._conversation_in_progress:
                return ReclaimResult(False, snapshot, reason="当前会话正在对话中")
            inactive_seconds = (
                max(0, int(now - self._last_activity_at))
                if self._last_activity_at is not None
                else 0
            )
            if inactive_seconds < self._inactive_timeout_seconds:
                remaining = max(
                    1,
                    int(
                        self._inactive_timeout_seconds
                        - inactive_seconds
                    ),
                )
                return ReclaimResult(
                    False,
                    snapshot,
                    reason=f"会话尚未闲置满5分钟，还需约{remaining}秒",
                )

            avatar_session_id = self._owner_avatar_session_id
            self._clear_owner()
            return ReclaimResult(
                True,
                self._snapshot(client_id),
                avatar_session_id=avatar_session_id,
            )

    async def snapshot(self, client_id: str | None = None) -> AccessSnapshot:
        async with self._lock:
            return self._snapshot(client_id)

    def _clear_owner(self) -> None:
        self._owner_id = None
        self._owner_avatar_session_id = None
        self._conversation_in_progress = False
        self._last_activity_at = None

    def _snapshot(self, client_id: str | None) -> AccessSnapshot:
        return AccessSnapshot(
            online_clients=len(self._client_connections),
            conversation_active=self._owner_id is not None,
            conversation_in_progress=self._conversation_in_progress,
            owns_conversation=self._owner_id == client_id,
        )
