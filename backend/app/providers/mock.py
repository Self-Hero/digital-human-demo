import asyncio
from collections.abc import AsyncIterator

from app.providers.contracts import AudioChunk


class MockLLMProvider:
    async def stream_reply(self, text: str) -> AsyncIterator[str]:
        response = (
            f"我收到了你的问题：{text}。"
            "当前运行的是前后端框架模拟链路，"
            "后续会依次接入线上大模型、流式语音和MuseTalk数字人。"
        )
        for index in range(0, len(response), 6):
            await asyncio.sleep(0.12)
            yield response[index : index + 6]


class MockTTSProvider:
    async def synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
        # Empty PCM is intentional: this phase validates scheduling, not playback.
        await asyncio.sleep(0.08)
        yield AudioChunk(sequence=0, pcm=b"", duration_ms=max(120, len(text) * 40))


class MockAvatarEngine:
    async def start(self, session_id: str) -> None:
        return None

    async def push_audio(self, session_id: str, turn_id: str, chunk: AudioChunk) -> None:
        await asyncio.sleep(min(chunk.duration_ms / 1000, 0.2))

    async def interrupt(self, session_id: str, turn_id: str) -> None:
        return None

    async def stop(self, session_id: str) -> None:
        return None
