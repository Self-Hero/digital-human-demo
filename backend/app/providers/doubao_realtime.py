import asyncio
import base64
import json
import time
from contextlib import suppress
from typing import Any
from uuid import uuid4

import websockets
from fastapi import WebSocket, WebSocketDisconnect

from app.core.config import Settings
from app.providers.livetalking import LiveTalkingAudioSink


class DoubaoRealtimeBridge:
    """Relay browser PCM audio to Doubao's duplex Realtime API."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._session_id = str(uuid4())
        self._event_sequence = 0
        self._upstream_send_lock = asyncio.Lock()

    def _new_event_id(self) -> str:
        self._event_sequence += 1
        return f"event_{self._event_sequence}"

    def _session_create_event(self) -> dict[str, Any]:
        return {
            "type": "session.create",
            "event_id": self._new_event_id(),
            "session": {
                "id": self._session_id,
                "model": self._settings.doubao_realtime_model,
                "instructions": self._settings.doubao_realtime_instructions,
                "audio": {
                    "input": {
                        "format": {
                            "type": self._settings.doubao_input_format,
                            "rate": 16_000,
                        }
                    },
                    "output": {
                        "format": {
                            "type": self._settings.doubao_output_format,
                            "rate": 24_000,
                        },
                        "voice": self._settings.doubao_realtime_voice,
                    },
                },
                "tools": [],
            },
            "extension": {
                "asr": {"extra": {}},
                "tts": {"extra": {}},
                "dialog": {
                    "extra": {
                        "enable_loudness_norm": True,
                        "enable_music": False,
                    }
                },
            },
        }

    async def _send_upstream(self, upstream: Any, event: dict[str, Any]) -> None:
        async with self._upstream_send_lock:
            await upstream.send(
                json.dumps(event, ensure_ascii=False, separators=(",", ":"))
            )

    async def _create_session(self, upstream: Any) -> None:
        await self._send_upstream(upstream, self._session_create_event())
        while True:
            raw_message = await asyncio.wait_for(upstream.recv(), timeout=15)
            event = json.loads(raw_message)
            event_type = str(event.get("type", ""))
            if event_type == "session.created":
                return
            if event_type == "error":
                error = event.get("error") or {}
                message = error.get("message") or error.get("code") or "未知错误"
                raise RuntimeError(f"豆包创建会话失败：{message}")

    async def run(self, browser: WebSocket) -> None:
        if not self._settings.doubao_api_key:
            await browser.send_json(
                {"type": "error", "message": "后端尚未配置 DOUBAO_API_KEY"}
            )
            return
        if self._settings.doubao_output_format != "pcm_s16le":
            await browser.send_json(
                {
                    "type": "error",
                    "message": "DOUBAO_OUTPUT_FORMAT 必须为 pcm_s16le",
                }
            )
            return

        headers = {"X-Api-Key": self._settings.doubao_api_key}
        browser_send_lock = asyncio.Lock()
        audio_sink = LiveTalkingAudioSink(self._settings)

        async def send(event: dict[str, Any]) -> None:
            async with browser_send_lock:
                await browser.send_json(event)

        try:
            async with websockets.connect(
                self._settings.doubao_realtime_url,
                additional_headers=headers,
                ping_interval=None,
                open_timeout=15,
                close_timeout=3,
                max_size=8 * 1024 * 1024,
            ) as upstream:
                await self._create_session(upstream)
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

                with suppress(Exception):
                    await self._send_upstream(
                        upstream,
                        {
                            "type": "session.close",
                            "event_id": self._new_event_id(),
                        },
                    )
        except WebSocketDisconnect:
            return
        except Exception as exc:
            with suppress(Exception):
                await send({"type": "error", "message": f"豆包实时连接失败：{exc}"})
        finally:
            await audio_sink.close()

    async def _forward_browser(
        self,
        browser: WebSocket,
        upstream: Any,
        send,
        audio_sink: LiveTalkingAudioSink,
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
                await self._send_upstream(
                    upstream,
                    {"type": "input_audio_buffer.append", "audio": audio},
                )
            elif message_type == "turn.interrupt":
                await self._send_upstream(
                    upstream,
                    {
                        "type": "response.cancel",
                        "event_id": self._new_event_id(),
                    },
                )
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
        upstream: Any,
        send,
        audio_sink: LiveTalkingAudioSink | None = None,
    ) -> None:
        speech_ended_at: float | None = None
        response_started_at: float | None = None
        first_audio_ms: int | None = None
        current_turn_id: str | None = None
        speaking = False
        user_speaking = False

        async for raw_message in upstream:
            event = json.loads(raw_message)
            event_type = str(event.get("type", ""))

            if event_type == "error":
                error = event.get("error") or {}
                await send(
                    {
                        "type": "error",
                        "message": error.get("message", "豆包返回未知错误"),
                    }
                )
                return
            if event_type == "session.closed":
                return
            if event_type == "conversation.item.input_audio_transcription.started":
                user_speaking = True
                speaking = False
                if audio_sink is not None:
                    await audio_sink.interrupt()
                await send({"type": "playback.clear"})
                await send({"type": "session.state", "state": "listening"})
            elif event_type == "conversation.item.input_audio_transcription.completed":
                user_speaking = False
                speech_ended_at = time.perf_counter()
                response_started_at = speech_ended_at
                first_audio_ms = None
                current_turn_id = str(uuid4())
                transcript = str(
                    event.get("transcript") or event.get("text") or ""
                ).strip()
                await send({"type": "turn.started", "turnId": current_turn_id})
                if transcript:
                    await send(
                        {
                            "type": "transcript.user",
                            "turnId": current_turn_id,
                            "text": transcript,
                        }
                    )
                await send({"type": "session.state", "state": "thinking"})
            elif event_type == "conversation.item.input_audio_transcription.failed":
                await send({"type": "error", "message": "豆包语音识别失败"})
            elif event_type == "response.output_text.delta":
                delta = str(event.get("delta", ""))
                if delta:
                    await send(
                        {
                            "type": "assistant.delta",
                            "turnId": current_turn_id,
                            "delta": delta,
                        }
                    )
            elif event_type == "response.output_text.done":
                await send(
                    {
                        "type": "assistant.done",
                        "turnId": current_turn_id,
                        "text": str(event.get("text", "")),
                    }
                )
            elif event_type == "response.output_audio.started":
                if not speaking:
                    speaking = True
                    await send({"type": "session.state", "state": "speaking"})
            elif event_type == "response.output_audio.delta":
                now = time.perf_counter()
                if first_audio_ms is None and speech_ended_at is not None:
                    first_audio_ms = int((now - speech_ended_at) * 1000)
                if not speaking:
                    speaking = True
                    await send({"type": "session.state", "state": "speaking"})
                delta = event.get("delta", "")
                if isinstance(delta, str) and delta:
                    await send(
                        {
                            "type": "audio.delta",
                            "turnId": current_turn_id,
                            "audio": delta,
                            "sampleRate": 24_000,
                        }
                    )
                    if audio_sink is not None:
                        await audio_sink.append(base64.b64decode(delta))
            elif event_type == "response.output_audio.done":
                if audio_sink is not None:
                    await audio_sink.flush()
            elif event_type == "response.canceled":
                speaking = False
                if audio_sink is not None:
                    await audio_sink.interrupt()
                await send({"type": "playback.clear"})
                await send(
                    {
                        "type": "session.state",
                        "state": "listening" if user_speaking else "idle",
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
                if current_turn_id is not None:
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
                await send(
                    {
                        "type": "session.state",
                        "state": "listening" if user_speaking else "idle",
                    }
                )
                speech_ended_at = None
                response_started_at = None
                current_turn_id = None
                speaking = False
