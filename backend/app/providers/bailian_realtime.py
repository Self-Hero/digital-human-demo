import asyncio
import base64
import json
import time
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import websockets
from fastapi import WebSocket, WebSocketDisconnect

from app.core.config import Settings
from app.providers.livetalking import LiveTalkingAudioSink


class BailianRealtimeBridge:
    """Relay browser PCM audio to Bailian without exposing the API key."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def run(self, browser: WebSocket) -> None:
        if not self._settings.bailian_api_key:
            await browser.send_json(
                {"type": "error", "message": "后端尚未配置 BAILIAN_API_KEY"}
            )
            return

        url = (
            f"{self._settings.bailian_realtime_url}"
            f"?model={quote(self._settings.bailian_realtime_model)}"
        )
        headers = {"Authorization": f"Bearer {self._settings.bailian_api_key}"}
        send_lock = asyncio.Lock()
        audio_sink = LiveTalkingAudioSink(self._settings)

        async def send(event: dict[str, Any]) -> None:
            async with send_lock:
                await browser.send_json(event)

        try:
            async with websockets.connect(
                url,
                additional_headers=headers,
                open_timeout=15,
                close_timeout=3,
                max_size=8 * 1024 * 1024,
            ) as upstream:
                await upstream.send(
                    json.dumps(
                        {
                            "type": "session.update",
                            "session": {
                                "modalities": ["text", "audio"],
                                "voice": self._settings.bailian_realtime_voice,
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
                await send(
                    {
                        "type": "realtime.ready",
                        "inputSampleRate": 16_000,
                        "outputSampleRate": 24_000,
                    }
                )
                await send({"type": "session.state", "state": "idle"})

                browser_task = asyncio.create_task(
                    self._forward_browser(browser, upstream, send, audio_sink)
                )
                upstream_task = asyncio.create_task(
                    self._forward_upstream(upstream, send, audio_sink)
                )
                done, pending = await asyncio.wait(
                    {browser_task, upstream_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                for task in done:
                    task.result()
        except WebSocketDisconnect:
            return
        except Exception as exc:
            try:
                await send({"type": "error", "message": f"百炼实时连接失败：{exc}"})
            except Exception:
                pass
        finally:
            await audio_sink.close()

    async def _forward_browser(
        self, browser: WebSocket, upstream: Any, send, audio_sink: LiveTalkingAudioSink
    ) -> None:
        async for message in self._browser_messages(browser):
            message_type = message.get("type")
            if message_type == "input_audio.append":
                audio = message.get("audio")
                if not isinstance(audio, str) or not audio:
                    continue
                if len(audio) > 256_000:
                    await send({"type": "error", "message": "单个音频分片过大"})
                    continue
                await upstream.send(
                    json.dumps(
                        {"type": "input_audio_buffer.append", "audio": audio}
                    )
                )
            elif message_type == "turn.interrupt":
                await upstream.send(json.dumps({"type": "response.cancel"}))
                await audio_sink.interrupt()
                await send({"type": "playback.clear"})
                await send({"type": "session.state", "state": "listening"})
            elif message_type == "avatar.session.attach":
                session_id = str(message.get("sessionId", "")).strip()
                if session_id:
                    audio_sink.attach(session_id)
                    await send({"type": "avatar.session.ready", "sessionId": session_id})
            elif message_type == "ping":
                await send({"type": "pong"})
            elif message_type == "realtime.stop":
                return

    @staticmethod
    async def _browser_messages(browser: WebSocket):
        while True:
            yield await browser.receive_json()

    @staticmethod
    async def _forward_upstream(
        upstream: Any, send, audio_sink: LiveTalkingAudioSink | None = None
    ) -> None:
        speech_ended_at: float | None = None
        response_started_at: float | None = None
        first_audio_ms: int | None = None
        current_turn_id: str | None = None
        speaking = False

        async for raw_message in upstream:
            event = json.loads(raw_message)
            event_type = str(event.get("type", ""))

            if event_type == "error":
                error = event.get("error") or {}
                await send(
                    {
                        "type": "error",
                        "message": error.get("message", "百炼返回未知错误"),
                    }
                )
            elif event_type == "input_audio_buffer.speech_started":
                await send({"type": "playback.clear"})
                await send({"type": "session.state", "state": "listening"})
            elif event_type == "input_audio_buffer.speech_stopped":
                speech_ended_at = time.perf_counter()
                response_started_at = speech_ended_at
                first_audio_ms = None
                current_turn_id = str(uuid4())
                speaking = False
                await send(
                    {
                        "type": "turn.started",
                        "turnId": current_turn_id,
                    }
                )
                await send({"type": "session.state", "state": "thinking"})
            elif event_type == "conversation.item.input_audio_transcription.completed":
                transcript = str(event.get("transcript", "")).strip()
                if transcript:
                    await send(
                        {
                            "type": "transcript.user",
                            "turnId": current_turn_id,
                            "text": transcript,
                        }
                    )
            elif event_type == "response.audio.delta":
                now = time.perf_counter()
                if first_audio_ms is None and speech_ended_at is not None:
                    first_audio_ms = int((now - speech_ended_at) * 1000)
                if not speaking:
                    speaking = True
                    await send({"type": "session.state", "state": "speaking"})
                await send(
                    {
                        "type": "audio.delta",
                        "turnId": current_turn_id,
                        "audio": event.get("delta", ""),
                        "sampleRate": 24_000,
                    }
                )
                if audio_sink is not None:
                    delta = event.get("delta", "")
                    if isinstance(delta, str) and delta:
                        await audio_sink.append(base64.b64decode(delta))
            elif event_type == "response.audio_transcript.delta":
                delta = str(event.get("delta", ""))
                if delta:
                    await send(
                        {
                            "type": "assistant.delta",
                            "turnId": current_turn_id,
                            "delta": delta,
                        }
                    )
            elif event_type == "response.audio_transcript.done":
                await send(
                    {
                        "type": "assistant.done",
                        "turnId": current_turn_id,
                        "text": str(event.get("transcript", "")),
                    }
                )
            elif event_type == "response.done":
                if audio_sink is not None:
                    await audio_sink.flush()
                now = time.perf_counter()
                total_ms = (
                    int((now - response_started_at) * 1000)
                    if response_started_at is not None
                    else 0
                )
                await send(
                    {
                        "type": "turn.completed",
                        "turnId": current_turn_id,
                        "metrics": {
                            "firstAudioMs": first_audio_ms,
                            "totalMs": total_ms,
                        },
                    }
                )
                await send({"type": "session.state", "state": "idle"})
                speech_ended_at = None
                response_started_at = None
                current_turn_id = None
                speaking = False
