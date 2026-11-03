import asyncio
import json
import logging
from urllib.parse import urlsplit, urlunsplit

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

from app.core.config import Settings

logger = logging.getLogger(__name__)


class LiveTalkingAudioSink:
    """Stream one continuous Realtime PCM turn into LiveTalking."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.livetalking_base_url.rstrip("/")
        self._websocket_url = self._make_websocket_url(self._base_url)
        self._sample_rate = 24_000
        self._session_id: str | None = None
        self._active_turn_id: str | None = None
        self._logged_pcm_turn_id: str | None = None
        self._socket = None
        self._lock = asyncio.Lock()
        self._client = httpx.AsyncClient(timeout=5.0)

    @staticmethod
    def _make_websocket_url(base_url: str) -> str:
        parsed = urlsplit(base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        path = f"{parsed.path.rstrip('/')}/humanpcm"
        return urlunsplit((scheme, parsed.netloc, path, "", ""))

    def attach(self, session_id: str) -> None:
        self._session_id = session_id

    async def append(self, pcm: bytes, turn_id: str) -> None:
        if not pcm or not self._session_id or not turn_id:
            return
        async with self._lock:
            if self._active_turn_id != turn_id:
                if self._active_turn_id is not None:
                    await self._finish_turn()
                await self._begin_turn(turn_id)
            await self._send_pcm(pcm)

    async def flush(self) -> None:
        async with self._lock:
            if self._active_turn_id is not None:
                await self._finish_turn()

    async def interrupt(self) -> None:
        async with self._lock:
            interrupted_over_socket = False
            if self._socket is not None and self._session_id:
                try:
                    await self._send_control(
                        {"type": "interrupt", "sessionid": self._session_id},
                        "interrupted",
                    )
                    interrupted_over_socket = True
                except (ConnectionClosed, OSError, TimeoutError, RuntimeError):
                    logger.warning(
                        "LiveTalking PCM socket failed during interrupt",
                        exc_info=True,
                    )
                    await self._reset_socket()
            self._active_turn_id = None
            self._logged_pcm_turn_id = None

            if not interrupted_over_socket and self._session_id:
                try:
                    response = await self._client.post(
                        f"{self._base_url}/interrupt_talk",
                        json={"sessionid": self._session_id},
                    )
                    response.raise_for_status()
                except httpx.HTTPError:
                    logger.exception("Failed to interrupt LiveTalking session")

    async def close(self) -> None:
        await self.interrupt()
        await self._reset_socket()
        await self._client.aclose()

    async def _begin_turn(self, turn_id: str) -> None:
        if not self._session_id:
            return
        command = {
            "type": "start",
            "sessionid": self._session_id,
            "turn_id": turn_id,
            "sample_rate": self._sample_rate,
            "sample_format": "pcm_s16le",
            "channels": 1,
        }
        try:
            await self._send_control(command, "started")
        except (ConnectionClosed, OSError, TimeoutError):
            await self._reset_socket()
            await self._send_control(command, "started")
        self._active_turn_id = turn_id
        logger.info("LiveTalking PCM turn started: %s", turn_id)

    async def _finish_turn(self) -> None:
        turn_id = self._active_turn_id
        if turn_id is None:
            return
        try:
            await self._send_control(
                {"type": "end", "turn_id": turn_id},
                "ended",
            )
            logger.info("LiveTalking PCM turn ended: %s", turn_id)
        except (ConnectionClosed, OSError, TimeoutError, RuntimeError):
            logger.exception("Failed to finish LiveTalking PCM turn %s", turn_id)
            await self._reset_socket()
        finally:
            self._active_turn_id = None
            self._logged_pcm_turn_id = None

    async def _send_pcm(self, pcm: bytes) -> None:
        try:
            socket = await self._open_socket()
            await socket.send(pcm)
            self._log_first_pcm_chunk(len(pcm))
        except (ConnectionClosed, OSError, TimeoutError):
            # Re-establish the same logical turn before retrying the lost chunk.
            turn_id = self._active_turn_id
            await self._reset_socket()
            self._active_turn_id = None
            if turn_id is None:
                raise
            await self._begin_turn(turn_id)
            socket = await self._open_socket()
            await socket.send(pcm)
            self._log_first_pcm_chunk(len(pcm))

    def _log_first_pcm_chunk(self, size: int) -> None:
        if self._active_turn_id == self._logged_pcm_turn_id:
            return
        logger.info(
            "LiveTalking first PCM chunk queued: turn=%s bytes=%s",
            self._active_turn_id,
            size,
        )
        self._logged_pcm_turn_id = self._active_turn_id

    async def _send_control(self, command: dict, expected_type: str) -> dict:
        socket = await self._open_socket()
        await socket.send(json.dumps(command, separators=(",", ":")))
        raw_response = await asyncio.wait_for(socket.recv(), timeout=5.0)
        if not isinstance(raw_response, str):
            raise RuntimeError("LiveTalking returned a non-JSON control response")
        response = json.loads(raw_response)
        if response.get("type") == "error":
            raise RuntimeError(
                f"LiveTalking PCM error: {response.get('message', 'unknown error')}"
            )
        if response.get("type") != expected_type:
            raise RuntimeError(
                "Unexpected LiveTalking PCM response: "
                f"expected {expected_type}, got {response.get('type')}"
            )
        return response

    async def _open_socket(self):
        if self._socket is None:
            self._socket = await websockets.connect(
                self._websocket_url,
                open_timeout=5,
                close_timeout=2,
                ping_interval=20,
                ping_timeout=20,
                max_size=1024 * 1024,
            )
        return self._socket

    async def _reset_socket(self) -> None:
        socket = self._socket
        self._socket = None
        if socket is not None:
            try:
                await socket.close()
            except (ConnectionClosed, OSError):
                pass
