from pathlib import Path

from scripts.configure_livetalking_gfpgan import (
    APP_IMPORT_ANCHOR,
    APP_WARMUP_ANCHOR,
    AVATAR_ANCHOR,
    IMPORT_ANCHOR,
    INFERENCE_ANCHOR,
    PASTE_ANCHOR,
    PATCHED_APP_IMPORT,
    PATCHED_APP_WARMUP,
    PATCHED_AVATAR,
    PATCHED_IMPORT,
    PATCHED_INFERENCE,
    PATCHED_PASTE,
    SYNC_INFERENCE,
    configure,
    configure_app,
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


def test_configure_app_preloads_gfpgan_once(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    original = (
        APP_IMPORT_ANCHOR
        + "\ndef main():\n"
        + "    if opt.model == 'musetalk':\n"
        + APP_WARMUP_ANCHOR
        + "\n"
    )
    source.write_text(original, encoding="utf-8")

    first_result = configure_app(source)
    first_text = source.read_text(encoding="utf-8")
    second_result = configure_app(source)

    assert first_result.startswith("configured; backup:")
    assert second_result == "already configured"
    assert first_text.count(PATCHED_APP_IMPORT) == 1
    assert first_text.count(PATCHED_APP_WARMUP) == 1
    assert source.with_suffix(".py.before-gfpgan-preload").read_text(
        encoding="utf-8"
    ) == original
