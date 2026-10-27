"""Run one short Bailian Realtime audio turn and record latency."""

import asyncio
import base64
import json
import sys
import time
import wave
from pathlib import Path
from urllib.parse import quote

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings


def read_pcm(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as source:
        if source.getnchannels() != 1 or source.getsampwidth() != 2:
            raise ValueError("Input must be mono 16-bit PCM WAV")
        return source.readframes(source.getnframes()), source.getframerate()


def write_pcm(path: Path, pcm: bytes, sample_rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        target.writeframes(pcm)


async def probe(input_path: Path, output_path: Path) -> int:
    settings = get_settings()
    if not settings.bailian_api_key:
        print("CONFIG_ERROR: BAILIAN_API_KEY is empty")
        return 2

    pcm, input_sample_rate = read_pcm(input_path)
    if input_sample_rate != 16_000:
        print(f"CONFIG_ERROR: input sample rate must be 16000 Hz, got {input_sample_rate}")
        return 2

    url = (
        f"{settings.bailian_realtime_url}"
        f"?model={quote(settings.bailian_realtime_model)}"
    )
    headers = {"Authorization": f"Bearer {settings.bailian_api_key}"}

    started_at = time.perf_counter()
    speech_ended_at: float | None = None
    first_audio_at: float | None = None
    completed_at: float | None = None
    output = bytearray()
    input_transcript = ""
    output_transcript = ""

    try:
        async with websockets.connect(
            url,
            additional_headers=headers,
            open_timeout=15,
            close_timeout=2,
            max_size=8 * 1024 * 1024,
        ) as websocket:
            connected_at = time.perf_counter()
            print(f"CONNECTED_MS: {(connected_at - started_at) * 1000:.0f}")

            # Match the official example: update immediately and let server VAD
            # commit the audio and create the response automatically.
            await websocket.send(
                json.dumps(
                    {
                        "type": "session.update",
                        "session": {
                            "modalities": ["text", "audio"],
                            "voice": settings.bailian_realtime_voice,
                            "turn_detection": {
                                "type": "server_vad",
                                "threshold": 0.5,
                                "silence_duration_ms": 500,
                            },
                        },
                    },
                    ensure_ascii=False,
                )
            )

            response_finished = asyncio.Event()

            async def receive_events() -> None:
                nonlocal first_audio_at, completed_at
                nonlocal input_transcript, output_transcript
                async for raw_message in websocket:
                    event = json.loads(raw_message)
                    event_type = str(event.get("type", "unknown"))

                    if event_type == "error":
                        error = event.get("error") or {}
                        raise RuntimeError(
                            f"{error.get('code', 'unknown')}: "
                            f"{error.get('message', 'unknown error')}"
                        )

                    if event_type == "session.created":
                        session = event.get("session") or {}
                        print(
                            "SESSION:",
                            json.dumps(
                                {
                                    "model": session.get("model"),
                                    "voice": session.get("voice"),
                                },
                                ensure_ascii=False,
                            ),
                        )
                    elif event_type == "response.audio.delta":
                        if first_audio_at is None:
                            first_audio_at = time.perf_counter()
                        output.extend(base64.b64decode(event.get("delta", "")))
                    elif event_type == "conversation.item.input_audio_transcription.completed":
                        input_transcript = str(event.get("transcript", ""))
                    elif event_type == "response.audio_transcript.done":
                        output_transcript = str(event.get("transcript", ""))
                    elif event_type in {"response.audio.done", "response.done"}:
                        completed_at = time.perf_counter()
                        response_finished.set()
                        if event_type == "response.done":
                            return

            receiver = asyncio.create_task(receive_events())

            # 3200 bytes is 100 ms of mono 16 kHz PCM16 audio.
            chunk_size = 3_200
            for offset in range(0, len(pcm), chunk_size):
                chunk = pcm[offset : offset + chunk_size]
                await websocket.send(
                    json.dumps(
                        {
                            "type": "input_audio_buffer.append",
                            "audio": base64.b64encode(chunk).decode("ascii"),
                        }
                    )
                )
                await asyncio.sleep(len(chunk) / (input_sample_rate * 2))

            speech_ended_at = time.perf_counter()

            # More than silence_duration_ms, so server VAD closes the turn.
            silence = bytes(input_sample_rate * 2)
            for offset in range(0, len(silence), chunk_size):
                chunk = silence[offset : offset + chunk_size]
                await websocket.send(
                    json.dumps(
                        {
                            "type": "input_audio_buffer.append",
                            "audio": base64.b64encode(chunk).decode("ascii"),
                        }
                    )
                )
                await asyncio.sleep(len(chunk) / (input_sample_rate * 2))

            try:
                await asyncio.wait_for(response_finished.wait(), timeout=30)
                # Audio completion can precede the final response metadata.
                if not receiver.done():
                    try:
                        await asyncio.wait_for(asyncio.shield(receiver), timeout=2)
                    except TimeoutError:
                        receiver.cancel()
            finally:
                if not receiver.done():
                    receiver.cancel()
                try:
                    await receiver
                except asyncio.CancelledError:
                    pass

        if not output or first_audio_at is None or speech_ended_at is None:
            print("PROBE_FAILED: response completed without audio")
            return 1

        completed_at = completed_at or time.perf_counter()
        output_sample_rate = 24_000
        write_pcm(output_path, bytes(output), output_sample_rate)
        audio_duration_ms = len(output) / (output_sample_rate * 2) * 1000

        print(f"FIRST_AUDIO_AFTER_SPEECH_MS: {(first_audio_at - speech_ended_at) * 1000:.0f}")
        print(f"FULL_RESPONSE_AFTER_SPEECH_MS: {(completed_at - speech_ended_at) * 1000:.0f}")
        print(f"OUTPUT_AUDIO_MS: {audio_duration_ms:.0f}")
        print(f"OUTPUT_BYTES: {len(output)}")
        if input_transcript:
            print(f"INPUT_TRANSCRIPT: {input_transcript}")
        if output_transcript:
            print(f"OUTPUT_TRANSCRIPT: {output_transcript}")
        print(f"OUTPUT_FILE: {output_path.resolve()}")
        print("PROBE_OK")
        return 0
    except Exception as exc:
        print(f"PROBE_ERROR: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    backend_root = Path(__file__).resolve().parents[1]
    raise SystemExit(
        asyncio.run(
            probe(
                backend_root / "output" / "realtime_input.wav",
                backend_root / "output" / "realtime_reply.wav",
            )
        )
    )
