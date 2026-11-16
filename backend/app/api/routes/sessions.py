import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel

from app.container import container
from app.core.config import Settings, get_settings
from app.providers.bailian_realtime import BailianRealtimeBridge
from app.providers.doubao_realtime import DoubaoRealtimeBridge
from app.services.sessions import new_turn_id

router = APIRouter(prefix="/sessions", tags=["sessions"])
CLIENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]{8,64}$")


class SessionCreateRequest(BaseModel):
    clientId: str | None = None


def create_realtime_bridge(
    settings: Settings,
    on_activity: Callable[[bool], Awaitable[None]] | None = None,
) -> BailianRealtimeBridge | DoubaoRealtimeBridge:
    provider = settings.realtime_provider.strip().lower()
    if provider == "doubao":
        return DoubaoRealtimeBridge(settings, on_activity)
    if provider == "bailian":
        return BailianRealtimeBridge(settings, on_activity)
    raise ValueError(f"Unsupported realtime provider: {settings.realtime_provider}")


@router.websocket("/{session_id}/realtime")
async def session_realtime(websocket: WebSocket, session_id: str) -> None:
    if container.sessions.get(session_id) is None:
        await websocket.close(code=4404, reason="Session not found")
        return

    await websocket.accept()

    async def on_activity(active: bool) -> None:
        session = container.sessions.get(session_id)
        if session is not None and session.client_id:
            await container.access.mark_activity(session.client_id, active)

    try:
        bridge = create_realtime_bridge(get_settings(), on_activity)
    except ValueError as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
        await container.sessions.remove(session_id)
        return
    try:
        await bridge.run(websocket)
    finally:
        await container.sessions.remove(session_id)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_session(
    request: SessionCreateRequest | None = None,
) -> dict[str, str]:
    client_id = request.clientId if request is not None else None
    if client_id is not None and not CLIENT_ID_PATTERN.fullmatch(client_id):
        raise HTTPException(status_code=400, detail="Invalid client id")
    session = await container.sessions.create(client_id)
    return {"sessionId": session.session_id}


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: str) -> None:
    removed = await container.sessions.remove(session_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Session not found")


@router.websocket("/{session_id}/events")
async def session_events(websocket: WebSocket, session_id: str) -> None:
    session = container.sessions.get(session_id)
    if session is None:
        await websocket.close(code=4404, reason="Session not found")
        return

    await websocket.accept()

    async def send(event: dict[str, Any]) -> None:
        async with session.send_lock:
            await websocket.send_json(event)

    await send({"type": "session.ready", "sessionId": session_id})
    await send({"type": "session.state", "state": "idle"})

    try:
        while True:
            message = await websocket.receive_json()
            message_type = message.get("type")

            if message_type == "user.text":
                text = str(message.get("text", "")).strip()
                if not text:
                    await send({"type": "error", "message": "消息不能为空"})
                    continue

                await container.sessions.interrupt(session)
                turn_id = new_turn_id()
                session.current_turn_id = turn_id
                session.current_task = asyncio.create_task(
                    container.orchestrator.run_text_turn(
                        session_id=session_id,
                        turn_id=turn_id,
                        text=text,
                        send=send,
                    )
                )
                continue

            if message_type == "turn.interrupt":
                await container.sessions.interrupt(session)
                continue

            if message_type == "ping":
                await send({"type": "pong"})
                continue

            await send({"type": "error", "message": f"不支持的消息类型：{message_type}"})
    except WebSocketDisconnect:
        await container.sessions.interrupt(session)
    except Exception:
        await container.sessions.interrupt(session)
        try:
            await send({"type": "error", "message": "会话连接发生异常"})
        except Exception:
            pass
