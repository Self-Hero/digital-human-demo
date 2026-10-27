"""Send one minimal OpenAI-compatible chat request to verify the API key."""

import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings


def main() -> int:
    settings = get_settings()
    if not settings.bailian_api_key:
        print("CONFIG_ERROR: BAILIAN_API_KEY is empty")
        return 2

    url = f"{settings.bailian_base_url.rstrip('/')}/chat/completions"
    started_at = time.perf_counter()
    try:
        response = httpx.post(
            url,
            headers={"Authorization": f"Bearer {settings.bailian_api_key}"},
            json={
                "model": "qwen3.8-flash",
                "messages": [{"role": "user", "content": "只回复OK"}],
                "max_tokens": 8,
                "temperature": 0,
            },
            timeout=20,
        )
    except Exception as exc:
        print(f"REQUEST_ERROR: {type(exc).__name__}: {exc}")
        return 1

    elapsed_ms = (time.perf_counter() - started_at) * 1000
    print(f"STATUS: {response.status_code}")
    print(f"ELAPSED_MS: {elapsed_ms:.0f}")
    if response.is_success:
        payload = response.json()
        choices = payload.get("choices") or []
        content = choices[0].get("message", {}).get("content", "") if choices else ""
        usage = payload.get("usage") or {}
        print(f"REPLY: {content}")
        print(f"USAGE: {usage}")
        print("PROBE_OK")
        return 0

    try:
        payload = response.json()
        error = payload.get("error", payload)
        print(f"API_ERROR: {error}")
    except ValueError:
        print(f"API_ERROR: {response.text[:500]}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
