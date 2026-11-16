import asyncio
import logging
import re
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status

from app.container import container
from app.core.config import get_settings
from app.services.conversation_access import AccessSnapshot

router = APIRouter(prefix="/access", tags=["access"])

CLIENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]{8,64}$")
AVATAR_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,128}$")
logger = logging.getLogger(__name__)


def _validate_client_id(client_id: str) -> None:
    if not CLIENT_ID_PATTERN.fullmatch(client_id):
        raise HTTPException(status_code=400, detail="Invalid client id")


def _payload(snapshot: AccessSnapshot) -> dict[str, int | bool]:
    return {
        "onlineClients": snapshot.online_clients,
        "conversationActive": snapshot.conversation_active,
        "conversationInProgress": snapshot.conversation_in_progress,
        "conversationReclaimable": snapshot.conversation_reclaimable,
        "conversationInactiveSeconds": snapshot.conversation_inactive_seconds,
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
            "当前数字人正在使用，请稍后再试"
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


@router.put("/conversation/{client_id}/avatar/{avatar_session_id}")
async def bind_avatar_session(
    client_id: str, avatar_session_id: str
) -> dict[str, int | bool]:
    _validate_client_id(client_id)
    if not AVATAR_SESSION_ID_PATTERN.fullmatch(avatar_session_id):
        raise HTTPException(status_code=400, detail="Invalid avatar session id")
    return _payload(
        await container.access.bind_avatar_session(client_id, avatar_session_id)
    )


@router.post("/conversation/{client_id}/reclaim")
async def reclaim_inactive_conversation(client_id: str) -> dict[str, int | bool]:
    _validate_client_id(client_id)
    result = await container.access.reclaim_inactive(client_id)
    if not result.reclaimed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=result.reason or "当前会话不能释放",
        )

    if result.avatar_session_id:
        session_id = quote(result.avatar_session_id, safe="")
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.delete(
                    f"{get_settings().livetalking_base_url.rstrip('/')}/session/{session_id}"
                )
                if response.status_code not in (200, 404):
                    logger.warning(
                        "LiveTalking session reclaim returned HTTP %s",
                        response.status_code,
                    )
        except httpx.HTTPError:
            logger.warning(
                "Could not directly close reclaimed LiveTalking session %s",
                result.avatar_session_id,
                exc_info=True,
            )

    return _payload(result.snapshot)
