from pathlib import Path

from scripts.configure_livetalking_silence_inference import (
    ENV_NAME,
    IDLE_FRAME_LINE,
    INIT_ANCHOR,
    PATCHED_IDLE_FRAME,
    PATCHED_SILENCE_CONDITION,
    SILENCE_CONDITION,
    configure,
)


def sample_source() -> str:
    return f'''import os
from queue import Queue

class BaseAvatar:
    def __init__(self, opt):
{INIT_ANCHOR.rstrip()}

    def inference(self, is_all_silence):
{SILENCE_CONDITION}
                return None
            return "generated"

    def process_frames(self, res_frame, idx):
        if self.custom_index.get(1) is not None:
            target_frame = self.custom_img_cycle[1][0]
        else:
{IDLE_FRAME_LINE}
        return target_frame
'''


def test_configure_enables_silence_inference_and_is_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "base_avatar.py"
    original = sample_source()
    source.write_text(original, encoding="utf-8")

    first_result = configure(source)
    first_text = source.read_text(encoding="utf-8")
    second_result = configure(source)

    assert first_result.startswith("configured; backup:")
    assert second_result == "already configured"
    assert ENV_NAME in first_text
    assert PATCHED_SILENCE_CONDITION in first_text
    assert PATCHED_IDLE_FRAME in first_text
    assert source.read_text(encoding="utf-8") == first_text
    assert source.with_suffix(".py.before-silence-inference").read_text(
        encoding="utf-8"
    ) == original


def test_configure_rejects_unknown_source_without_modifying_it(tmp_path: Path) -> None:
    source = tmp_path / "base_avatar.py"
    original = "class BaseAvatar:\n    pass\n"
    source.write_text(original, encoding="utf-8")

    try:
        configure(source)
    except RuntimeError as exc:
        assert "Expected one BaseAvatar initialization block" in str(exc)
    else:
        raise AssertionError("configure() should reject an unknown source layout")

    assert source.read_text(encoding="utf-8") == original
