import asyncio
import base64
import gzip
import json
from collections.abc import AsyncIterator

from app.api.routes.sessions import create_realtime_bridge
from app.core.config import Settings
from app.providers.bailian_realtime import BailianRealtimeBridge
from app.providers.doubao_legacy_protocol import (
    GZIP,
    JSON,
    MSG_WITH_EVENT,
    NO_SERIALIZATION,
    SERVER_ACK,
    SERVER_FULL_RESPONSE,
    generate_header,
    parse_response,
)
from app.providers.doubao_realtime import DoubaoRealtimeBridge


class FakeUpstream:
    def __init__(self, messages: list[bytes]) -> None:
        self._messages = messages

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[bytes]:
        for message in self._messages:
            yield message


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


def server_message(
    *,
    event: int | None = None,
    payload: dict | bytes | None = None,
    message_type: int = SERVER_FULL_RESPONSE,
) -> bytes:
    is_audio = isinstance(payload, bytes)
    serialization = NO_SERIALIZATION if is_audio else JSON
    raw = payload if is_audio else json.dumps(payload or {}).encode()
    compressed = gzip.compress(raw)
    flags = MSG_WITH_EVENT if event is not None else 0
    frame = bytearray(
        generate_header(
            message_type=message_type,
            flags=flags,
            serialization=serialization,
            compression=GZIP,
        )
    )
    if event is not None:
        frame.extend(event.to_bytes(4, "big"))
    session_id = b"test-session"
    frame.extend(len(session_id).to_bytes(4, "big"))
    frame.extend(session_id)
    frame.extend(len(compressed).to_bytes(4, "big"))
    frame.extend(compressed)
    return bytes(frame)


def test_legacy_headers_and_session_contract() -> None:
    settings = Settings(
        _env_file=None,
        doubao_app_id="app-id",
        doubao_access_key="access-key",
        doubao_app_key="app-key",
        doubao_realtime_voice="S_clone",
        doubao_character_manifest="沉稳可靠",
    )
    bridge = DoubaoRealtimeBridge(settings)

    headers = bridge._headers()
    session = bridge._session_payload()

    assert headers["X-Api-App-ID"] == "app-id"
    assert headers["X-Api-Access-Key"] == "access-key"
    assert headers["X-Api-Resource-Id"] == "volc.speech.dialog"
    assert headers["X-Api-App-Key"] == "app-key"
    assert headers["X-Api-Connect-Id"]
    assert session["tts"]["speaker"] == "S_clone"
    assert session["tts"]["audio_config"] == {
        "channel": 1,
        "format": "pcm_s16le",
        "sample_rate": 24_000,
    }
    assert session["dialog"]["character_manifest"] == "沉稳可靠"
    assert session["dialog"]["extra"]["input_mod"] == "audio"


def test_binary_audio_response_is_decoded() -> None:
    pcm = b"\x01\x00\x02\x00"
    message = parse_response(
        server_message(payload=pcm, message_type=SERVER_ACK)
    )

    assert message.message_type == SERVER_ACK
    assert message.session_id == "test-session"
    assert message.payload == pcm


def test_upstream_events_are_mapped_to_browser_and_livetalking() -> None:
    received: list[dict] = []
    sink = FakeAudioSink()
    pcm = b"\x01\x00\x02\x00"
    bridge = DoubaoRealtimeBridge(Settings(_env_file=None))

    async def send(event: dict) -> None:
        received.append(event)

    upstream = FakeUpstream(
        [
            server_message(event=450),
            server_message(event=451, payload={"transcript": "你"}),
            server_message(event=459, payload={"transcript": "你好"}),
            server_message(event=550, payload={"content": "你好"}),
            server_message(payload=pcm, message_type=SERVER_ACK),
            server_message(event=359),
        ]
    )

    asyncio.run(bridge._forward_upstream(upstream, send, sink))

    event_types = [event["type"] for event in received]
    assert "playback.clear" in event_types
    assert "transcript.user" in event_types
    assert "assistant.delta" in event_types
    assert "assistant.done" in event_types
    assert "audio.delta" in event_types
    assert "turn.completed" in event_types
    assert received[-1] == {"type": "session.state", "state": "idle"}
    audio_event = next(event for event in received if event["type"] == "audio.delta")
    assert base64.b64decode(audio_event["audio"]) == pcm
    assert sink.appended == [pcm]
    assert sink.interrupt_count == 1
    assert sink.flush_count == 1


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
