from pathlib import Path

from scripts.configure_livetalking_keyframes import (
    PATCHED_TRACK,
    TRACK_ANCHOR,
    configure,
)


def test_configure_keyframes_is_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "rtc_manager.py"
    original = (
        "import json\nimport asyncio\n\n"
        "class RTCManager:\n"
        "    async def create(self):\n"
        + TRACK_ANCHOR
        + "codec_preferences = []\n"
    )
    source.write_text(original, encoding="utf-8")

    first_result = configure(source)
    first_text = source.read_text(encoding="utf-8")
    second_result = configure(source)

    assert first_result.startswith("configured; backup:")
    assert second_result == "already configured"
    assert PATCHED_TRACK in first_text
    assert "import os\n" in first_text
    assert 'LIVETALKING_VIDEO_KEYFRAME_INTERVAL", "2.0"' in first_text
    assert source.with_suffix(".py.before-keyframe-config").read_text(
        encoding="utf-8"
    ) == original


def test_configure_keyframes_reuses_existing_os_import(tmp_path: Path) -> None:
    source = tmp_path / "rtc_manager.py"
    source.write_text(
        "import json\nimport asyncio\nimport os\n\n" + TRACK_ANCHOR,
        encoding="utf-8",
    )

    configure(source)

    assert source.read_text(encoding="utf-8").count("import os\n") == 1


def test_configure_keyframes_rejects_unknown_rtc_manager(tmp_path: Path) -> None:
    source = tmp_path / "rtc_manager.py"
    source.write_text("class RTCManager:\n    pass\n", encoding="utf-8")

    try:
        configure(source)
    except RuntimeError as exc:
        assert "track anchors" in str(exc)
    else:
        raise AssertionError("configure() should reject an unknown source layout")
