from pathlib import Path

from scripts.configure_livetalking_video import (
    IMPORT_ANCHOR,
    ORIGINAL_METHOD,
    PATCHED_METHOD,
    configure,
)


def test_configure_resizes_video_and_is_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "webrtc.py"
    original = IMPORT_ANCHOR + "\n\nclass HumanPlayer:\n" + ORIGINAL_METHOD
    source.write_text(original, encoding="utf-8")

    first_result = configure(source)
    first_text = source.read_text(encoding="utf-8")
    second_result = configure(source)

    assert first_result.startswith("configured; backup:")
    assert second_result == "already configured"
    assert PATCHED_METHOD in first_text
    assert 'LIVETALKING_VIDEO_WIDTH", "720"' in first_text
    assert 'LIVETALKING_VIDEO_HEIGHT", "1280"' in first_text
    assert source.read_text(encoding="utf-8") == first_text
    assert source.with_suffix(".py.before-720p").read_text(encoding="utf-8") == original


def test_configure_rejects_unknown_livetalking_source(tmp_path: Path) -> None:
    source = tmp_path / "webrtc.py"
    original = IMPORT_ANCHOR + "\nclass HumanPlayer:\n    pass\n"
    source.write_text(original, encoding="utf-8")

    try:
        configure(source)
    except RuntimeError as exc:
        assert "Could not find HumanPlayer.push_video()" in str(exc)
    else:
        raise AssertionError("configure() should reject an unknown source layout")

    assert source.read_text(encoding="utf-8") == original
