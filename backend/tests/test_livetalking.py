import asyncio
import io
import wave

from app.core.config import Settings
from app.providers.livetalking import LiveTalkingAudioSink


def test_pcm_is_wrapped_as_mono_24khz_wav() -> None:
    sink = LiveTalkingAudioSink(Settings())
    pcm = b"\x00\x00" * 2_400

    wav_data = sink._wrap_wav(pcm)
    with wave.open(io.BytesIO(wav_data), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 24_000
        assert wav_file.getnframes() == 2_400

    asyncio.run(sink.close())
