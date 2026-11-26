from pathlib import Path

from scripts.configure_livetalking_frame_transitions import (
    OUTPUT_ANCHOR,
    PATCHED_OUTPUT,
    PATCHED_SPEAKING,
    PATCHED_STATE,
    SPEAKING_ANCHOR,
    STATE_ANCHOR,
    configure,
)


def test_configure_frame_transitions_is_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "base_avatar.py"
    original = (
        "class BaseAvatar:\n"
        "    def process_frames(self):\n"
        "        enable_transition = False\n"
        + STATE_ANCHOR
        + "        while True:\n"
        "            audio_frames = []\n"
        + SPEAKING_ANCHOR
        + "            combine_frame = None\n"
        + OUTPUT_ANCHOR
        + "            break\n"
    )
    source.write_text(original, encoding="utf-8")

    first_result = configure(source)
    first_text = source.read_text(encoding="utf-8")
    second_result = configure(source)

    assert first_result.startswith("configured; backup:")
    assert second_result == "already configured"
    assert PATCHED_STATE in first_text
    assert PATCHED_SPEAKING in first_text
    assert PATCHED_OUTPUT in first_text
    assert source.with_suffix(".py.before-frame-transitions").read_text(
        encoding="utf-8"
    ) == original
