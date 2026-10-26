import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from app.providers.contracts import AvatarEngine, LLMProvider, TTSProvider

EventSender = Callable[[dict], Awaitable[None]]
logger = logging.getLogger(__name__)


class ConversationOrchestrator:
    def __init__(
        self,
        llm: LLMProvider,
        tts: TTSProvider,
        avatar: AvatarEngine,
    ) -> None:
        self._llm = llm
        self._tts = tts
        self._avatar = avatar

    async def run_text_turn(
        self,
        session_id: str,
        turn_id: str,
        text: str,
        send: EventSender,
    ) -> None:
        started = time.perf_counter()
        first_delta_ms: int | None = None
        full_reply = ""

        try:
            await send({"type": "turn.started", "turnId": turn_id})
            await send({"type": "transcript.user", "turnId": turn_id, "text": text})
            await send({"type": "session.state", "state": "thinking", "turnId": turn_id})

            async for delta in self._llm.stream_reply(text):
                if first_delta_ms is None:
                    first_delta_ms = int((time.perf_counter() - started) * 1000)
                full_reply += delta
                await send(
                    {
                        "type": "assistant.delta",
                        "turnId": turn_id,
                        "delta": delta,
                    }
                )

            await send({"type": "session.state", "state": "speaking", "turnId": turn_id})
            async for audio_chunk in self._tts.synthesize(full_reply):
                await self._avatar.push_audio(session_id, turn_id, audio_chunk)
                await send(
                    {
                        "type": "audio.chunk",
                        "turnId": turn_id,
                        "sequence": audio_chunk.sequence,
                        "durationMs": audio_chunk.duration_ms,
                    }
                )

            total_ms = int((time.perf_counter() - started) * 1000)
            await send({"type": "assistant.done", "turnId": turn_id, "text": full_reply})
            await send(
                {
                    "type": "turn.completed",
                    "turnId": turn_id,
                    "metrics": {"firstDeltaMs": first_delta_ms, "totalMs": total_ms},
                }
            )
            await send({"type": "session.state", "state": "idle", "turnId": turn_id})
        except asyncio.CancelledError:
            await self._avatar.interrupt(session_id, turn_id)
            await send({"type": "turn.interrupted", "turnId": turn_id})
            await send({"type": "session.state", "state": "idle", "turnId": turn_id})
            raise
        except Exception:
            logger.exception("Conversation turn failed", extra={"turn_id": turn_id})
            await send({"type": "error", "turnId": turn_id, "message": "当前回答处理失败，请重试"})
            await send({"type": "session.state", "state": "idle", "turnId": turn_id})
