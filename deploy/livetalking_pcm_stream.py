"""Raw PCM WebSocket input for a LiveTalking avatar session."""

from __future__ import annotations

import json
import os

import numpy as np
import soxr
from aiohttp import WSMsgType, web

from server.session_manager import session_manager
from utils.logger import logger


class PcmTurn:
    """Convert one continuous PCM turn into LiveTalking's 20 ms frames."""

    def __init__(self, avatar_session, sample_rate: int, turn_id: str) -> None:
        self.avatar_session = avatar_session
        self.turn_id = turn_id
        self.frame_samples = avatar_session.chunk
        prebuffer_ms = max(
            20,
            min(1_000, int(os.getenv("LIVETALKING_PCM_PREBUFFER_MS", "200"))),
        )
        self.prebuffer_samples = avatar_session.sample_rate * prebuffer_ms // 1000
        self.pending = np.empty(0, dtype=np.float32)
        self.first_frame = True
        self.resampler = soxr.ResampleStream(
            sample_rate,
            avatar_session.sample_rate,
            1,
            dtype="float32",
            quality="HQ",
        )

    def append(self, pcm: bytes) -> None:
        if len(pcm) % 2:
            raise ValueError("PCM payload must contain complete signed 16-bit samples")
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        if samples.size:
            self._append_resampled(self.resampler.resample_chunk(samples, last=False))
            self._emit_complete_frames()

    def finish(self) -> None:
        empty = np.empty(0, dtype=np.float32)
        self._append_resampled(self.resampler.resample_chunk(empty, last=True))
        self._emit_complete_frames(force=True)

        # LiveTalking consumes an explicit final frame to close the turn. This
        # occurs once per complete answer, never at transport chunk boundaries.
        final_frame = np.zeros(self.frame_samples, dtype=np.float32)
        if self.pending.size:
            final_frame[: self.pending.size] = self.pending
        if self.first_frame:
            self.avatar_session.put_audio_frame(
                final_frame,
                {"status": "start", "turn_id": self.turn_id},
            )
            final_frame = np.zeros(self.frame_samples, dtype=np.float32)
        self.avatar_session.put_audio_frame(
            final_frame,
            {"status": "end", "turn_id": self.turn_id},
        )
        self.pending = np.empty(0, dtype=np.float32)
        self.first_frame = False

    def _append_resampled(self, samples: np.ndarray) -> None:
        samples = np.asarray(samples, dtype=np.float32).reshape(-1)
        if not samples.size:
            return
        self.pending = (
            np.concatenate((self.pending, samples))
            if self.pending.size
            else samples
        )

    def _emit_complete_frames(self, force: bool = False) -> None:
        if (
            self.first_frame
            and not force
            and self.pending.size < self.prebuffer_samples
        ):
            return
        offset = 0
        while self.pending.size - offset >= self.frame_samples:
            event = {"turn_id": self.turn_id}
            if self.first_frame:
                event["status"] = "start"
                self.first_frame = False
                logger.info("PCM turn %s emitted its first audio frame", self.turn_id)
            frame = self.pending[offset : offset + self.frame_samples]
            self.avatar_session.put_audio_frame(frame, event)
            offset += self.frame_samples
        if offset:
            self.pending = self.pending[offset:]


async def pcm_stream(request: web.Request) -> web.WebSocketResponse:
    """Receive one or more complete 24 kHz PCM turns over one WebSocket."""

    websocket = web.WebSocketResponse(heartbeat=30, max_msg_size=1024 * 1024)
    await websocket.prepare(request)
    turn: PcmTurn | None = None
    last_session = None

    async def send_error(message: str) -> None:
        await websocket.send_json({"type": "error", "message": message})

    try:
        async for message in websocket:
            if message.type == WSMsgType.BINARY:
                if turn is None:
                    await send_error("Send a start message before PCM data")
                    continue
                try:
                    turn.append(message.data)
                except ValueError as exc:
                    await send_error(str(exc))
                continue

            if message.type != WSMsgType.TEXT:
                if message.type == WSMsgType.ERROR:
                    logger.warning("PCM WebSocket error: %s", websocket.exception())
                continue

            try:
                command = json.loads(message.data)
            except (TypeError, json.JSONDecodeError):
                await send_error("Control messages must be valid JSON")
                continue

            command_type = command.get("type")
            if command_type == "start":
                session_id = str(command.get("sessionid", "")).strip()
                turn_id = str(command.get("turn_id", "")).strip()
                try:
                    sample_rate = int(command.get("sample_rate", 0))
                except (TypeError, ValueError):
                    await send_error("sample_rate must be an integer")
                    continue
                if not session_id or not turn_id:
                    await send_error("start requires sessionid and turn_id")
                    continue
                if command.get("sample_format") != "pcm_s16le":
                    await send_error("sample_format must be pcm_s16le")
                    continue
                if command.get("channels") != 1:
                    await send_error("channels must be 1")
                    continue
                if not 8_000 <= sample_rate <= 48_000:
                    await send_error("sample_rate must be between 8000 and 48000")
                    continue
                avatar_session = session_manager.get_session(session_id)
                if avatar_session is None:
                    await send_error("session not found")
                    continue
                if turn is not None:
                    turn.avatar_session.flush_talk()
                last_session = avatar_session
                turn = PcmTurn(avatar_session, sample_rate, turn_id)
                await websocket.send_json({"type": "started", "turn_id": turn_id})
            elif command_type == "end":
                if turn is None:
                    await send_error("no active PCM turn")
                    continue
                requested_turn_id = str(command.get("turn_id", "")).strip()
                if requested_turn_id != turn.turn_id:
                    await send_error("end turn_id does not match the active turn")
                    continue
                turn_id = turn.turn_id
                turn.finish()
                turn = None
                await websocket.send_json({"type": "ended", "turn_id": turn_id})
            elif command_type == "interrupt":
                if turn is not None:
                    last_session = turn.avatar_session
                if last_session is not None:
                    last_session.flush_talk()
                turn = None
                await websocket.send_json({"type": "interrupted"})
            elif command_type == "ping":
                await websocket.send_json({"type": "pong"})
            else:
                await send_error(f"unknown control message: {command_type}")
    finally:
        if turn is not None:
            # A broken producer must not leave stale speech queued.
            turn.avatar_session.flush_talk()

    return websocket
