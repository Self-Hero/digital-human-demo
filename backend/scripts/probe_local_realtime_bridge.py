"""Verify the local API can establish Bailian Realtime without sending audio."""

import asyncio
import json

import httpx
import websockets


async def main() -> None:
    api_url = "http://127.0.0.1:8001/api/v1"
    session_id = httpx.post(f"{api_url}/sessions", timeout=5).json()["sessionId"]
    try:
        url = f"ws://127.0.0.1:8001/api/v1/sessions/{session_id}/realtime"
        async with websockets.connect(url, open_timeout=10) as websocket:
            event = json.loads(await asyncio.wait_for(websocket.recv(), timeout=10))
            print(event)
            if event.get("type") != "realtime.ready":
                raise RuntimeError(f"Unexpected first event: {event}")
    finally:
        httpx.delete(f"{api_url}/sessions/{session_id}", timeout=5)


if __name__ == "__main__":
    asyncio.run(main())
