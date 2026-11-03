import asyncio
import json

from app.core.config import Settings
from app.providers import livetalking
from app.providers.livetalking import LiveTalkingAudioSink


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[str | bytes] = []
        self.responses: list[str] = []
        self.closed = False

    async def send(self, message: str | bytes) -> None:
        self.sent.append(message)
        if isinstance(message, str):
            command = json.loads(message)
            response_types = {
                "start": "started",
                "end": "ended",
                "interrupt": "interrupted",
            }
            response_type = response_types.get(command["type"], "error")
            self.responses.append(json.dumps({"type": response_type}))

    async def recv(self) -> str:
        return self.responses.pop(0)

    async def close(self) -> None:
        self.closed = True


def test_pcm_socket_url_tracks_livetalking_base_url() -> None:
    sink = LiveTalkingAudioSink(
        Settings(_env_file=None, livetalking_base_url="https://avatar.test/base/")
    )

    assert sink._websocket_url == "wss://avatar.test/base/humanpcm"

    asyncio.run(sink.close())


def test_one_turn_uses_one_start_and_one_end(monkeypatch) -> None:
    socket = FakeSocket()

    async def connect(*args, **kwargs):
        return socket

    monkeypatch.setattr(livetalking.websockets, "connect", connect)
    sink = LiveTalkingAudioSink(Settings(_env_file=None))
    sink.attach("avatar-session")

    async def run() -> None:
        await sink.append(b"\x01\x00" * 480, "turn-1")
        await sink.append(b"\x02\x00" * 480, "turn-1")
        await sink.flush()
        await sink.close()

    asyncio.run(run())

    controls = [json.loads(item) for item in socket.sent if isinstance(item, str)]
    binary = [item for item in socket.sent if isinstance(item, bytes)]
    assert [item["type"] for item in controls] == ["start", "end", "interrupt"]
    assert controls[0] == {
        "type": "start",
        "sessionid": "avatar-session",
        "turn_id": "turn-1",
        "sample_rate": 24_000,
        "sample_format": "pcm_s16le",
        "channels": 1,
    }
    assert controls[1] == {"type": "end", "turn_id": "turn-1"}
    assert binary == [b"\x01\x00" * 480, b"\x02\x00" * 480]
    assert socket.closed


def test_turn_change_finishes_previous_turn(monkeypatch) -> None:
    socket = FakeSocket()

    async def connect(*args, **kwargs):
        return socket

    monkeypatch.setattr(livetalking.websockets, "connect", connect)
    sink = LiveTalkingAudioSink(Settings(_env_file=None))
    sink.attach("avatar-session")

    async def run() -> None:
        await sink.append(b"\x01\x00", "turn-1")
        await sink.append(b"\x02\x00", "turn-2")
        await sink.flush()

    asyncio.run(run())

    controls = [
        json.loads(item)["type"] for item in socket.sent if isinstance(item, str)
    ]
    assert controls == ["start", "end", "start", "end"]
