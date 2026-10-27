"""Minimal, low-cost connectivity probe for Bailian Realtime.

The probe sends one very short text turn and closes as soon as the first audio
delta arrives. It never prints the API key or returned audio payload.
"""

import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import quote

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings


async def probe() -> int:
    settings = get_settings()
    if not settings.bailian_api_key:
        print("CONFIG_ERROR: BAILIAN_API_KEY is empty")
        return 2

    url = (
        f"{settings.bailian_realtime_url}"
        f"?model={quote(settings.bailian_realtime_model)}"
    )
    headers = {
        "Authorization": f"Bearer {settings.bailian_api_key}",
        "OpenAI-Beta": "realtime=v1",
    }

    try:
        async with websockets.connect(
            url,
            additional_headers=headers,
            open_timeout=10,
            close_timeout=2,
            max_size=2 * 1024 * 1024,
        ) as websocket:
            print("CONNECTED")

            initial_event = json.loads(await asyncio.wait_for(websocket.recv(), timeout=5))
            initial_type = str(initial_event.get("type", "unknown"))
            print(f"EVENT: {initial_type}")
            if initial_type == "error":
                error = initial_event.get("error") or {}
                print("API_ERROR:", error.get("code", "unknown"), error.get("message", "unknown error"))
                return 1

            await websocket.send(
                json.dumps(
                    {
                        "type": "session.update",
                        "session": {
                            "modalities": ["text", "audio"],
                            "instructions": "只回复一个字：好。不要继续解释。",
                            "voice": settings.bailian_realtime_voice,
                            "input_audio_format": "pcm16",
                            "output_audio_format": "pcm24",
                            "max_response_output_tokens": 8,
                        },
                    },
                    ensure_ascii=False,
                )
            )

            session_ready = False
            async with asyncio.timeout(5):
                while not session_ready:
                    event = json.loads(await websocket.recv())
                    event_type = str(event.get("type", "unknown"))
                    print(f"EVENT: {event_type}")
                    if event_type == "error":
                        error = event.get("error") or {}
                        print("API_ERROR:", error.get("code", "unknown"), error.get("message", "unknown error"))
                        return 1
                    session_ready = event_type == "session.updated"

            await websocket.send(
                json.dumps(
                    {
                        "type": "conversation.item.create",
                        "item": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "你好"}],
                        },
                    },
                    ensure_ascii=False,
                )
            )
            await websocket.send(
                json.dumps(
                    {
                        "type": "response.create",
                        "response": {"modalities": ["audio", "text"]},
                    }
                )
            )

            async with asyncio.timeout(20):
                async for raw_message in websocket:
                    event = json.loads(raw_message)
                    event_type = str(event.get("type", "unknown"))

                    if event_type == "error":
                        error = event.get("error") or {}
                        print(
                            "API_ERROR:",
                            error.get("code", "unknown"),
                            error.get("message", "unknown error"),
                        )
                        return 1

                    if event_type in {
                        "response.audio.delta",
                        "response.output_audio.delta",
                    }:
                        delta = event.get("delta", "")
                        print(f"AUDIO_DELTA: {len(delta)} base64 characters")
                        print("PROBE_OK")
                        return 0

                    if event_type in {
                        "session.created",
                        "session.updated",
                        "response.created",
                        "response.text.delta",
                        "response.audio_transcript.delta",
                    }:
                        print(f"EVENT: {event_type}")
                    elif event_type not in {"response.audio.delta", "response.output_audio.delta"}:
                        print(f"EVENT: {event_type}")

    except TimeoutError:
        print("TIMEOUT: no audio delta received within 20 seconds")
        return 1
    except Exception as exc:
        print(f"CONNECTION_ERROR: {type(exc).__name__}: {exc}")
        return 1

    print("CONNECTION_CLOSED: no audio delta received")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(probe()))
