import asyncio
from dataclasses import dataclass, field
from uuid import uuid4

from app.providers.contracts import AvatarEngine


@dataclass
class SessionRuntime:
    session_id: str
    current_turn_id: str | None = None
    current_task: asyncio.Task[None] | None = None
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class SessionManager:
    def __init__(self, avatar: AvatarEngine) -> None:
        self._avatar = avatar
        self._sessions: dict[str, SessionRuntime] = {}

    async def create(self) -> SessionRuntime:
        session = SessionRuntime(session_id=str(uuid4()))
        self._sessions[session.session_id] = session
        await self._avatar.start(session.session_id)
        return session

    def get(self, session_id: str) -> SessionRuntime | None:
        return self._sessions.get(session_id)

    async def interrupt(self, session: SessionRuntime) -> None:
        task = session.current_task
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        session.current_task = None

    async def remove(self, session_id: str) -> bool:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        await self.interrupt(session)
        await self._avatar.stop(session_id)
        return True

    async def close_all(self) -> None:
        for session_id in list(self._sessions):
            await self.remove(session_id)


def new_turn_id() -> str:
    return str(uuid4())
