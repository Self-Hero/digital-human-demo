import asyncio
import json
from collections.abc import AsyncIterator

from app.core.config import Settings
from app.providers.bailian_realtime import BailianRealtimeBridge


class FakeUpstream:
    def __init__(self, events: list[dict]) -> None:
        self._events = events

    def __aiter__(self) -> AsyncIterator[str]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[str]:
        for event in self._events:
            yield json.dumps(event)


class FakeAudioSink:
    def __init__(self) -> None:
        self.appended: list[tuple[bytes, str]] = []
        self.flush_count = 0

    async def append(self, pcm: bytes, turn_id: str) -> None:
        self.appended.append((pcm, turn_id))

    async def flush(self) -> None:
        self.flush_count += 1


def test_upstream_events_are_mapped_to_browser_protocol() -> None:
    received: list[dict] = []
    activity: list[bool] = []
    sink = FakeAudioSink()

    async def send(event: dict) -> None:
        received.append(event)

    async def on_activity(active: bool) -> None:
        activity.append(active)

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

    bridge = BailianRealtimeBridge(Settings(_env_file=None), on_activity)
    asyncio.run(bridge._forward_upstream(upstream, send, sink))

    event_types = [event["type"] for event in received]
    assert "playback.clear" in event_types
    assert "transcript.user" in event_types
    assert "assistant.delta" in event_types
    assert "audio.delta" not in event_types
    assert "turn.completed" in event_types
    assert len(sink.appended) == 1
    assert sink.appended[0][0] == b"\x00"
    assert sink.appended[0][1]
    assert sink.flush_count == 1
    assert activity == [True, False]
    assert received[-1] == {"type": "session.state", "state": "idle"}
