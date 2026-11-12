from pathlib import Path

from scripts.configure_livetalking_session_cleanup import (
    APP_HANDLER_ANCHOR,
    APP_ROUTE_ANCHOR,
    HANDLER_ANCHOR,
    MAX_SESSION_RESPONSE_ANCHOR,
    OFFER_ANCHOR,
    PATCHED_HANDLER,
    PATCHED_APP_HANDLER,
    PATCHED_APP_ROUTE,
    PATCHED_MAX_SESSION_RESPONSE,
    PATCHED_OFFER,
    configure,
    configure_app,
)


def test_configure_session_cleanup_is_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "rtc_manager.py"
    original = (
        "import asyncio\n\n"
        "class RTCManager:\n"
        "    async def make(self):\n"
        + HANDLER_ANCHOR
        + "\n    async def offer(self):\n"
        + "        try:\n"
        + "            pass\n"
        + "        except MaxSessionError as e:\n"
        + MAX_SESSION_RESPONSE_ANCHOR
        + OFFER_ANCHOR
        + "            text='ok',\n"
        + "        )\n"
    )
    source.write_text(original, encoding="utf-8")

    first_result = configure(source)
    updated = source.read_text(encoding="utf-8")
    second_result = configure(source)

    assert first_result.startswith("configured; backup:")
    assert second_result == "already configured"
    assert PATCHED_HANDLER in updated
    assert PATCHED_MAX_SESSION_RESPONSE in updated
    assert PATCHED_OFFER in updated
    assert source.with_suffix(".py.before-session-cleanup").read_text(
        encoding="utf-8"
    ) == original


def test_configure_app_adds_explicit_session_close(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    original = (
        "import json\nfrom aiohttp import web\n\n"
        + APP_HANDLER_ANCHOR
        + "    pass\n\n"
        + "def main():\n"
        + APP_ROUTE_ANCHOR
    )
    source.write_text(original, encoding="utf-8")

    first_result = configure_app(source)
    updated = source.read_text(encoding="utf-8")
    second_result = configure_app(source)

    assert first_result.startswith("configured; backup:")
    assert second_result == "already configured"
    assert PATCHED_APP_HANDLER in updated
    assert PATCHED_APP_ROUTE in updated
