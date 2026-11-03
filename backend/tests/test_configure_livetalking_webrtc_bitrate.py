from pathlib import Path

from scripts.configure_livetalking_webrtc_bitrate import (
    IMPORT_ANCHOR,
    LOGGER_ANCHOR,
    PATCHED_CONFIG,
    PATCHED_IMPORT,
    configure,
)


def test_configure_webrtc_bitrate_is_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "rtc_manager.py"
    original = IMPORT_ANCHOR + "\n" + LOGGER_ANCHOR + "class RTCManager:\n    pass\n"
    source.write_text(original, encoding="utf-8")

    first_result = configure(source)
    first_text = source.read_text(encoding="utf-8")
    second_result = configure(source)

    assert first_result.startswith("configured; backup:")
    assert second_result == "already configured"
    assert PATCHED_IMPORT in first_text
    assert PATCHED_CONFIG in first_text
    assert 'LIVETALKING_VIDEO_BITRATE_INITIAL", "3000000"' in first_text
    assert 'LIVETALKING_VIDEO_BITRATE_MAX", "6000000"' in first_text
    assert source.with_suffix(".py.before-bitrate-config").read_text(
        encoding="utf-8"
    ) == original


def test_configure_rejects_unknown_rtc_manager(tmp_path: Path) -> None:
    source = tmp_path / "rtc_manager.py"
    source.write_text("class RTCManager:\n    pass\n", encoding="utf-8")

    try:
        configure(source)
    except RuntimeError as exc:
        assert "bitrate anchors" in str(exc)
    else:
        raise AssertionError("configure() should reject an unknown source layout")
