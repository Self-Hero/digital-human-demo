from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class AudioChunk:
    sequence: int
    pcm: bytes
    sample_rate: int = 16_000
    duration_ms: int = 0


class ASRProvider(Protocol):
    async def transcribe(self, audio: AsyncIterator[bytes]) -> AsyncIterator[str]: ...


class LLMProvider(Protocol):
    async def stream_reply(self, text: str) -> AsyncIterator[str]: ...


class TTSProvider(Protocol):
    async def synthesize(self, text: str) -> AsyncIterator[AudioChunk]: ...


class AvatarEngine(Protocol):
    async def start(self, session_id: str) -> None: ...

    async def push_audio(self, session_id: str, turn_id: str, chunk: AudioChunk) -> None: ...

    async def interrupt(self, session_id: str, turn_id: str) -> None: ...

    async def stop(self, session_id: str) -> None: ...
