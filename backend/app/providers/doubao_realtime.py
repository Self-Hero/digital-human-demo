import asyncio
import base64
import binascii
import logging
import time
from contextlib import suppress
from typing import Any
from uuid import uuid4

import websockets
from fastapi import WebSocket, WebSocketDisconnect

from app.core.config import Settings
from app.providers.doubao_legacy_protocol import (
    SERVER_ACK,
    ServerMessage,
    encode_audio_request,
    encode_json_request,
    parse_response,
)
from app.providers.livetalking import LiveTalkingAudioSink

logger = logging.getLogger(__name__)


class DoubaoRealtimeBridge:
    """Bridge browser PCM to Doubao's legacy binary realtime dialogue API."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._session_id = str(uuid4())
        self._upstream_send_lock = asyncio.Lock()
        self._suppress_audio = False
        self._user_speaking = False
        self._speaking = False
        self._current_turn_id: str | None = None
        self._user_transcript = ""
        self._assistant_text = ""
        self._speech_ended_at: float | None = None
        self._response_started_at: float | None = None
        self._first_audio_ms: int | None = None

    def _headers(self) -> dict[str, str]:
        return {
            "X-Api-App-ID": self._settings.doubao_app_id,
            "X-Api-Access-Key": self._settings.doubao_access_key,
            "X-Api-Resource-Id": self._settings.doubao_resource_id,
            "X-Api-App-Key": self._settings.doubao_app_key,
            "X-Api-Connect-Id": str(uuid4()),
        }

    def _session_payload(self) -> dict[str, Any]:
        dialog: dict[str, Any] = {
            "bot_name": self._settings.doubao_bot_name,
            "system_role": self._settings.doubao_system_role,
            "speaking_style": self._settings.doubao_speaking_style,
            "location": {"city": self._settings.doubao_location_city},
            "extra": {
                "strict_audit": False,
                "audit_response": self._settings.doubao_audit_response,
                "recv_timeout": self._settings.doubao_recv_timeout,
                "input_mod": "audio",
            },
        }
        if self._settings.doubao_character_manifest.strip():
            dialog["character_manifest"] = (
                self._settings.doubao_character_manifest.strip()
            )
        return {
            "asr": {"extra": {"end_smooth_window_ms": 1_500}},
            "tts": {
                "speaker": self._settings.doubao_realtime_voice,
                "audio_config": {
                    "channel": 1,
                    "format": "pcm_s16le",
                    "sample_rate": 24_000,
                },
            },
            "dialog": dialog,
        }

    async def _send_upstream(self, upstream: Any, frame: bytes) -> None:
        async with self._upstream_send_lock:
            await upstream.send(frame)

    async def _start_upstream_session(self, upstream: Any) -> None:
        await self._send_upstream(upstream, encode_json_request(1, {}))
        self._raise_for_server_message(parse_response(await upstream.recv()))
        await self._send_upstream(
            upstream,
            encode_json_request(
                100,
                self._session_payload(),
                session_id=self._session_id,
            ),
        )
        self._raise_for_server_message(parse_response(await upstream.recv()))

    @staticmethod
    def _raise_for_server_message(message: ServerMessage) -> None:
        if not message.is_error:
            return
        detail = message.payload
        if isinstance(detail, dict):
            detail = detail.get("message") or detail.get("error") or detail
        raise RuntimeError(f"豆包服务错误 {message.error_code}: {detail}")

    async def run(self, browser: WebSocket) -> None:
        missing = [
            name
            for name, value in {
                "DOUBAO_APP_ID": self._settings.doubao_app_id,
                "DOUBAO_ACCESS_KEY": self._settings.doubao_access_key,
                "DOUBAO_RESOURCE_ID": self._settings.doubao_resource_id,
                "DOUBAO_APP_KEY": self._settings.doubao_app_key,
            }.items()
            if not value.strip()
        ]
        if missing:
            await browser.send_json(
                {"type": "error", "message": f"后端尚未配置：{', '.join(missing)}"}
            )
            return

        browser_send_lock = asyncio.Lock()
        audio_sink = LiveTalkingAudioSink(self._settings)

        async def send(event: dict[str, Any]) -> None:
            async with browser_send_lock:
                await browser.send_json(event)

        try:
            async with websockets.connect(
                self._settings.doubao_realtime_url,
                additional_headers=self._headers(),
                ping_interval=None,
                open_timeout=15,
                close_timeout=3,
                max_size=8 * 1024 * 1024,
            ) as upstream:
                await asyncio.wait_for(
                    self._start_upstream_session(upstream), timeout=15
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

                with suppress(Exception):
                    await self._send_upstream(
                        upstream,
                        encode_json_request(102, {}, session_id=self._session_id),
                    )
                    await self._send_upstream(upstream, encode_json_request(2, {}))
        except WebSocketDisconnect:
            return
        except Exception as exc:
            logger.exception("Doubao legacy realtime connection failed")
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
                try:
                    pcm = base64.b64decode(audio, validate=True)
                except (binascii.Error, ValueError):
                    await send({"type": "error", "message": "音频分片不是有效 Base64"})
                    continue
                await self._send_upstream(
                    upstream,
                    encode_audio_request(200, self._session_id, pcm),
                )
            elif message_type == "turn.interrupt":
                self._suppress_audio = True
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

    async def _forward_upstream(
        self,
        upstream: Any,
        send,
        audio_sink: LiveTalkingAudioSink,
    ) -> None:
        async for raw_message in upstream:
            message = parse_response(raw_message)
            self._raise_for_server_message(message)
            if message.message_type == SERVER_ACK and isinstance(message.payload, bytes):
                await self._handle_audio(message.payload, send, audio_sink)
                continue
            should_stop = await self._handle_event(message, send, audio_sink)
            if should_stop:
                return

    async def _handle_audio(self, pcm: bytes, send, audio_sink) -> None:
        if not pcm or self._suppress_audio:
            return
        if self._current_turn_id is None:
            self._start_turn()
            await send({"type": "turn.started", "turnId": self._current_turn_id})
        now = time.perf_counter()
        if self._first_audio_ms is None and self._speech_ended_at is not None:
            self._first_audio_ms = int((now - self._speech_ended_at) * 1000)
        if not self._speaking:
            self._speaking = True
            await send({"type": "session.state", "state": "speaking"})
        await send(
            {
                "type": "audio.delta",
                "turnId": self._current_turn_id,
                "audio": base64.b64encode(pcm).decode("ascii"),
                "sampleRate": 24_000,
            }
        )
        await audio_sink.append(pcm)

    async def _handle_event(self, message: ServerMessage, send, audio_sink) -> bool:
        event = message.event
        payload = message.payload if isinstance(message.payload, dict) else {}
        if event is None:
            return False
        logger.info("Doubao legacy event=%s payload=%s", event, payload)

        if event == 450:
            self._user_speaking = True
            self._suppress_audio = True
            self._speaking = False
            self._user_transcript = ""
            await audio_sink.interrupt()
            await send({"type": "playback.clear"})
            await send({"type": "session.state", "state": "listening"})
        elif 451 <= event < 459:
            text = self._extract_text(payload)
            if text:
                self._user_transcript = self._merge_text(
                    self._user_transcript, text
                )[0]
        elif event == 459:
            self._user_speaking = False
            self._suppress_audio = False
            text = self._extract_text(payload)
            if text:
                self._user_transcript = self._merge_text(
                    self._user_transcript, text
                )[0]
            self._start_turn()
            await send({"type": "turn.started", "turnId": self._current_turn_id})
            if self._user_transcript:
                await send(
                    {
                        "type": "transcript.user",
                        "turnId": self._current_turn_id,
                        "text": self._user_transcript,
                    }
                )
            await send({"type": "session.state", "state": "thinking"})
        elif 550 <= event < 559 or event in {350, 351}:
            text = self._extract_text(payload)
            if text:
                if self._current_turn_id is None:
                    self._start_turn()
                    await send(
                        {"type": "turn.started", "turnId": self._current_turn_id}
                    )
                self._assistant_text, delta = self._merge_text(
                    self._assistant_text, text
                )
                if delta:
                    await send(
                        {
                            "type": "assistant.delta",
                            "turnId": self._current_turn_id,
                            "delta": delta,
                        }
                    )
        elif event == 359:
            await self._complete_turn(send, audio_sink)
        elif event == 152:
            await self._complete_turn(send, audio_sink)
            return True
        elif event == 153:
            raise RuntimeError(f"豆包会话失败：{payload}")
        return False

    def _start_turn(self) -> None:
        now = time.perf_counter()
        self._current_turn_id = str(uuid4())
        self._speech_ended_at = now
        self._response_started_at = now
        self._first_audio_ms = None
        self._assistant_text = ""

    async def _complete_turn(self, send, audio_sink) -> None:
        if self._current_turn_id is None:
            self._speaking = False
            return
        await audio_sink.flush()
        if self._assistant_text:
            await send(
                {
                    "type": "assistant.done",
                    "turnId": self._current_turn_id,
                    "text": self._assistant_text,
                }
            )
        total_ms = (
            int((time.perf_counter() - self._response_started_at) * 1000)
            if self._response_started_at is not None
            else 0
        )
        await send(
            {
                "type": "turn.completed",
                "turnId": self._current_turn_id,
                "metrics": {
                    "firstAudioMs": self._first_audio_ms,
                    "totalMs": total_ms,
                },
            }
        )
        await send(
            {
                "type": "session.state",
                "state": "listening" if self._user_speaking else "idle",
            }
        )
        self._current_turn_id = None
        self._speech_ended_at = None
        self._response_started_at = None
        self._first_audio_ms = None
        self._assistant_text = ""
        self._speaking = False
        self._suppress_audio = False

    @classmethod
    def _extract_text(cls, value: Any) -> str:
        if not isinstance(value, (dict, list)):
            return ""
        if isinstance(value, list):
            return "".join(cls._extract_text(item) for item in value).strip()
        for key in ("transcript", "utterance", "content", "text", "reply", "answer"):
            text = value.get(key)
            if isinstance(text, str) and text.strip():
                return text.strip()
        for key in ("result", "data", "message", "response", "results"):
            text = cls._extract_text(value.get(key))
            if text:
                return text
        return ""

    @staticmethod
    def _merge_text(current: str, incoming: str) -> tuple[str, str]:
        incoming = incoming.strip()
        if not incoming:
            return current, ""
        if incoming.startswith(current):
            return incoming, incoming[len(current) :]
        if current.endswith(incoming):
            return current, ""
        return current + incoming, incoming
