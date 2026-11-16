import asyncio
import re

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status

from app.container import container
from app.services.conversation_access import AccessSnapshot

router = APIRouter(prefix="/access", tags=["access"])

CLIENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]{8,64}$")


def _validate_client_id(client_id: str) -> None:
    if not CLIENT_ID_PATTERN.fullmatch(client_id):
        raise HTTPException(status_code=400, detail="Invalid client id")


def _payload(snapshot: AccessSnapshot) -> dict[str, int | bool]:
    return {
        "onlineClients": snapshot.online_clients,
        "conversationActive": snapshot.conversation_active,
        "ownsConversation": snapshot.owns_conversation,
    }


@router.websocket("/presence/{client_id}")
async def presence(websocket: WebSocket, client_id: str) -> None:
    if not CLIENT_ID_PATTERN.fullmatch(client_id):
        await websocket.close(code=4400, reason="Invalid client id")
        return

    await websocket.accept()
    await container.access.connect(client_id)
    try:
        while True:
            snapshot = await container.access.snapshot(client_id)
            await websocket.send_json(_payload(snapshot))
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=2.0)
            except TimeoutError:
                continue
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await container.access.disconnect(client_id)


@router.post("/conversation/{client_id}")
async def acquire_conversation(client_id: str) -> dict[str, int | bool]:
    _validate_client_id(client_id)
    acquired, snapshot = await container.access.acquire(client_id)
    if not acquired:
        detail = (
            "当前已有用户正在对话，请稍后再试"
            if snapshot.conversation_active
            else "页面连接已失效，请刷新后重试"
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
        )
    return _payload(snapshot)


@router.delete("/conversation/{client_id}")
async def release_conversation(client_id: str) -> dict[str, int | bool]:
    _validate_client_id(client_id)
    return _payload(await container.access.release(client_id))
