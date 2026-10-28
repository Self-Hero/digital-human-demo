import asyncio
import io
import logging
import wave

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)


class LiveTalkingAudioSink:
    """Buffer Realtime PCM into short WAV chunks for a LiveTalking session."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.livetalking_base_url.rstrip("/")
        self._sample_rate = 24_000
        # LiveTalking treats every upload as a standalone audio segment. Very
        # short WAV files do not reliably switch MuseTalk out of its idle loop.
        chunk_ms = max(2_000, settings.livetalking_audio_chunk_ms)
        self._chunk_bytes = (
            self._sample_rate * 2 * chunk_ms // 1000
        )
        self._session_id: str | None = None
        self._buffer = bytearray()
        self._lock = asyncio.Lock()
        self._client = httpx.AsyncClient(timeout=5.0)

    def attach(self, session_id: str) -> None:
        self._session_id = session_id

    async def append(self, pcm: bytes) -> None:
        if not pcm or not self._session_id:
            return
        async with self._lock:
            self._buffer.extend(pcm)
            while len(self._buffer) >= self._chunk_bytes:
                chunk = bytes(self._buffer[: self._chunk_bytes])
                del self._buffer[: self._chunk_bytes]
                await self._upload(chunk)

    async def flush(self) -> None:
        async with self._lock:
            if self._buffer and self._session_id:
                chunk = bytes(self._buffer)
                self._buffer.clear()
                await self._upload(chunk)

    async def interrupt(self) -> None:
        async with self._lock:
            self._buffer.clear()
            if not self._session_id:
                return
            try:
                await self._client.post(
                    f"{self._base_url}/interrupt_talk",
                    json={"sessionid": self._session_id},
                )
            except httpx.HTTPError:
                logger.exception("Failed to interrupt LiveTalking session")

    async def close(self) -> None:
        await self.interrupt()
        await self._client.aclose()

    async def _upload(self, pcm: bytes) -> None:
        if not self._session_id:
            return
        wav_data = self._wrap_wav(pcm)
        try:
            response = await self._client.post(
                f"{self._base_url}/humanaudio",
                data={"sessionid": self._session_id},
                files={"file": ("realtime.wav", wav_data, "audio/wav")},
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") != 0:
                logger.error("LiveTalking rejected audio: %s", payload)
        except (httpx.HTTPError, ValueError):
            logger.exception("Failed to upload audio to LiveTalking")

    def _wrap_wav(self, pcm: bytes) -> bytes:
        output = io.BytesIO()
        with wave.open(output, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self._sample_rate)
            wav_file.writeframes(pcm)
        return output.getvalue()
