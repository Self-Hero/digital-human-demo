import gzip
import json
from dataclasses import dataclass
from typing import Any

PROTOCOL_VERSION = 0b0001

CLIENT_FULL_REQUEST = 0b0001
CLIENT_AUDIO_ONLY_REQUEST = 0b0010
SERVER_FULL_RESPONSE = 0b1001
SERVER_ACK = 0b1011
SERVER_ERROR_RESPONSE = 0b1111

MSG_WITH_EVENT = 0b0100

NO_SERIALIZATION = 0b0000
JSON = 0b0001

GZIP = 0b0001


@dataclass(frozen=True)
class ServerMessage:
    message_type: int
    event: int | None = None
    session_id: str | None = None
    payload: Any = None
    sequence: int | None = None
    error_code: int | None = None

    @property
    def is_error(self) -> bool:
        return self.message_type == SERVER_ERROR_RESPONSE


def generate_header(
    *,
    message_type: int = CLIENT_FULL_REQUEST,
    flags: int = MSG_WITH_EVENT,
    serialization: int = JSON,
    compression: int = GZIP,
) -> bytes:
    return bytes(
        [
            (PROTOCOL_VERSION << 4) | 1,
            (message_type << 4) | flags,
            (serialization << 4) | compression,
            0,
        ]
    )


def encode_json_request(
    event: int,
    payload: dict[str, Any],
    *,
    session_id: str | None = None,
) -> bytes:
    body = gzip.compress(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    )
    frame = bytearray(generate_header())
    frame.extend(event.to_bytes(4, "big"))
    if session_id is not None:
        session = session_id.encode()
        frame.extend(len(session).to_bytes(4, "big"))
        frame.extend(session)
    frame.extend(len(body).to_bytes(4, "big"))
    frame.extend(body)
    return bytes(frame)


def encode_audio_request(event: int, session_id: str, pcm: bytes) -> bytes:
    payload = gzip.compress(pcm)
    session = session_id.encode()
    frame = bytearray(
        generate_header(
            message_type=CLIENT_AUDIO_ONLY_REQUEST,
            serialization=NO_SERIALIZATION,
        )
    )
    frame.extend(event.to_bytes(4, "big"))
    frame.extend(len(session).to_bytes(4, "big"))
    frame.extend(session)
    frame.extend(len(payload).to_bytes(4, "big"))
    frame.extend(payload)
    return bytes(frame)


def parse_response(data: bytes | str) -> ServerMessage:
    if isinstance(data, str):
        raise ValueError("豆包旧版协议返回了文本帧，预期为二进制帧")
    if len(data) < 4:
        raise ValueError("豆包旧版协议帧头不完整")

    header_size = (data[0] & 0x0F) * 4
    if header_size < 4 or len(data) < header_size:
        raise ValueError("豆包旧版协议帧头长度无效")

    message_type = data[1] >> 4
    flags = data[1] & 0x0F
    serialization = data[2] >> 4
    compression = data[2] & 0x0F
    payload = memoryview(data)[header_size:]
    offset = 0

    def take_u32() -> int:
        nonlocal offset
        if len(payload) < offset + 4:
            raise ValueError("豆包旧版协议帧长度不完整")
        value = int.from_bytes(payload[offset : offset + 4], "big")
        offset += 4
        return value

    if message_type == SERVER_ERROR_RESPONSE:
        error_code = take_u32()
        payload_size = take_u32()
        raw_payload = bytes(payload[offset : offset + payload_size])
        decoded = _decode_payload(raw_payload, serialization, compression)
        return ServerMessage(
            message_type=message_type,
            payload=decoded,
            error_code=error_code,
        )

    if message_type not in {SERVER_FULL_RESPONSE, SERVER_ACK}:
        return ServerMessage(message_type=message_type, payload=bytes(payload))

    sequence = take_u32() if flags & 0b0011 else None
    event = take_u32() if flags & MSG_WITH_EVENT else None
    session_size = take_u32()
    if len(payload) < offset + session_size:
        raise ValueError("豆包旧版协议 session ID 长度无效")
    session_id = bytes(payload[offset : offset + session_size]).decode(
        "utf-8", errors="replace"
    )
    offset += session_size
    payload_size = take_u32()
    if len(payload) < offset + payload_size:
        raise ValueError("豆包旧版协议 payload 长度无效")
    raw_payload = bytes(payload[offset : offset + payload_size])
    decoded = _decode_payload(raw_payload, serialization, compression)
    return ServerMessage(
        message_type=message_type,
        event=event,
        session_id=session_id,
        payload=decoded,
        sequence=sequence,
    )


def _decode_payload(raw: bytes, serialization: int, compression: int) -> Any:
    if compression == GZIP and raw:
        raw = gzip.decompress(raw)
    if serialization == JSON and raw:
        return json.loads(raw.decode("utf-8"))
    if serialization == NO_SERIALIZATION:
        return raw
    return raw.decode("utf-8", errors="replace")
