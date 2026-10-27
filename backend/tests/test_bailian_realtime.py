import asyncio
import json
from collections.abc import AsyncIterator

from app.providers.bailian_realtime import BailianRealtimeBridge


class FakeUpstream:
    def __init__(self, events: list[dict]) -> None:
        self._events = events

    def __aiter__(self) -> AsyncIterator[str]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[str]:
        for event in self._events:
            yield json.dumps(event)


def test_upstream_events_are_mapped_to_browser_protocol() -> None:
    received: list[dict] = []

    async def send(event: dict) -> None:
        received.append(event)

    upstream = FakeUpstream(
        [
            {"type": "input_audio_buffer.speech_started"},
            {"type": "input_audio_buffer.speech_stopped"},
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "transcript": "你好",
            },
            {"type": "response.audio_transcript.delta", "delta": "你"},
            {"type": "response.audio.delta", "delta": "AA=="},
            {"type": "response.audio_transcript.done", "transcript": "你好"},
            {"type": "response.done"},
        ]
    )

    asyncio.run(BailianRealtimeBridge._forward_upstream(upstream, send))

    event_types = [event["type"] for event in received]
    assert "playback.clear" in event_types
    assert "transcript.user" in event_types
    assert "assistant.delta" in event_types
    assert "audio.delta" in event_types
    assert "turn.completed" in event_types
    assert received[-1] == {"type": "session.state", "state": "idle"}
