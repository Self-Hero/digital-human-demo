from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class AudioChunk:
    sequence: int
    pcm: bytes
    sample_rate: int = 16_000
    duration_ms: int = 0


@dataclass(slots=True)
class RealtimeAudioEvent:
    type: str
    turn_id: str | None = None
    audio: bytes | None = None
    transcript: str | None = None
    sample_rate: int | None = None


class RealtimeAudioProvider(Protocol):
    async def connect(self, session_id: str) -> None: ...

    async def send_audio(self, session_id: str, audio: bytes) -> None: ...

    async def events(self, session_id: str) -> AsyncIterator[RealtimeAudioEvent]: ...

    async def interrupt(self, session_id: str, turn_id: str | None = None) -> None: ...

    async def close(self, session_id: str) -> None: ...


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
