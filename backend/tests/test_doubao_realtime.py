import asyncio
import base64
import json
from collections.abc import AsyncIterator

from app.api.routes.sessions import create_realtime_bridge
from app.core.config import Settings
from app.providers.bailian_realtime import BailianRealtimeBridge
from app.providers.doubao_realtime import DoubaoRealtimeBridge


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
        self.appended: list[bytes] = []
        self.flush_count = 0
        self.interrupt_count = 0

    async def append(self, pcm: bytes) -> None:
        self.appended.append(pcm)

    async def flush(self) -> None:
        self.flush_count += 1

    async def interrupt(self) -> None:
        self.interrupt_count += 1


def test_session_create_uses_duplex_pcm_contract() -> None:
    settings = Settings(_env_file=None)
    bridge = DoubaoRealtimeBridge(settings)

    event = bridge._session_create_event()

    assert event["type"] == "session.create"
    assert event["session"]["model"] == "1.2.6.1"
    assert event["session"]["audio"]["input"]["format"] == {
        "type": "pcm",
        "rate": 16_000,
    }
    assert event["session"]["audio"]["output"]["format"] == {
        "type": "pcm_s16le",
        "rate": 24_000,
    }


def test_upstream_events_are_mapped_to_browser_and_livetalking() -> None:
    received: list[dict] = []
    sink = FakeAudioSink()
    pcm = b"\x01\x00\x02\x00"

    async def send(event: dict) -> None:
        received.append(event)

    upstream = FakeUpstream(
        [
            {"type": "conversation.item.input_audio_transcription.started"},
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "transcript": "你好",
            },
            {"type": "response.output_text.delta", "delta": "你"},
            {"type": "response.output_text.done", "text": "你好"},
            {"type": "response.output_audio.started"},
            {
                "type": "response.output_audio.delta",
                "delta": base64.b64encode(pcm).decode("ascii"),
            },
            {"type": "response.output_audio.done"},
            {"type": "response.done"},
        ]
    )

    asyncio.run(DoubaoRealtimeBridge._forward_upstream(upstream, send, sink))

    event_types = [event["type"] for event in received]
    assert "playback.clear" in event_types
    assert "transcript.user" in event_types
    assert "assistant.delta" in event_types
    assert "assistant.done" in event_types
    assert "audio.delta" in event_types
    assert "turn.completed" in event_types
    assert received[-1] == {"type": "session.state", "state": "idle"}
    assert sink.appended == [pcm]
    assert sink.interrupt_count == 1
    assert sink.flush_count == 2


def test_realtime_provider_can_fall_back_to_bailian() -> None:
    doubao = create_realtime_bridge(
        Settings(_env_file=None, realtime_provider="doubao")
    )
    bailian = create_realtime_bridge(
        Settings(_env_file=None, realtime_provider="bailian")
    )

    assert isinstance(doubao, DoubaoRealtimeBridge)
    assert isinstance(bailian, BailianRealtimeBridge)


def test_unknown_realtime_provider_is_rejected() -> None:
    settings = Settings(_env_file=None, realtime_provider="unknown")

    try:
        create_realtime_bridge(settings)
    except ValueError as exc:
        assert "Unsupported realtime provider" in str(exc)
    else:
        raise AssertionError("unknown realtime provider should fail")
