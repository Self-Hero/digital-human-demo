from pathlib import Path

from scripts.configure_livetalking_gfpgan import (
    AVATAR_ANCHOR,
    IMPORT_ANCHOR,
    INFERENCE_ANCHOR,
    PASTE_ANCHOR,
    PATCHED_AVATAR,
    PATCHED_IMPORT,
    PATCHED_INFERENCE,
    PATCHED_PASTE,
    SYNC_INFERENCE,
    configure,
)


def test_configure_gfpgan_is_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "musetalk_avatar.py"
    original = (
        IMPORT_ANCHOR
        + "\nclass MuseReal:\n"
        + "    def __init__(self):\n"
        + AVATAR_ANCHOR
        + "\n    def inference_batch(self):\n"
        + INFERENCE_ANCHOR
        + "\n"
        + PASTE_ANCHOR
    )
    source.write_text(original, encoding="utf-8")

    first_result = configure(source)
    first_text = source.read_text(encoding="utf-8")
    second_result = configure(source)

    assert first_result.startswith("configured; backup:")
    assert second_result == "already configured"
    assert PATCHED_IMPORT in first_text
    assert PATCHED_AVATAR in first_text
    assert PATCHED_INFERENCE in first_text
    assert PATCHED_PASTE in first_text
    assert source.with_suffix(".py.before-gfpgan").read_text(encoding="utf-8") == original


def test_configure_migrates_synchronous_hook(tmp_path: Path) -> None:
    source = tmp_path / "musetalk_avatar.py"
    original = (
        PATCHED_IMPORT
        + "\nclass MuseReal:\n"
        + "    def __init__(self):\n"
        + PATCHED_AVATAR
        + "\n    def inference_batch(self):\n"
        + SYNC_INFERENCE
        + "\n"
        + PASTE_ANCHOR
    )
    source.write_text(original, encoding="utf-8")

    configure(source)
    updated = source.read_text(encoding="utf-8")

    assert SYNC_INFERENCE not in updated
    assert PATCHED_INFERENCE in updated
    assert PATCHED_PASTE in updated
