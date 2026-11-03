from pathlib import Path

from scripts.configure_livetalking_mouth_stabilizer import (
    AVATAR_ANCHOR,
    BLEND_ANCHOR,
    IMPORT_ANCHOR,
    LEGACY_PATCHED_BLEND,
    PATCHED_AVATAR,
    PATCHED_BLEND,
    PATCHED_IMPORT,
    configure,
)


def test_configure_mouth_stabilizer_is_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "musetalk_avatar.py"
    original = (
        IMPORT_ANCHOR
        + "\nclass MuseReal:\n"
        + "    def __init__(self, opt, avatar):\n"
        + AVATAR_ANCHOR
        + "\n    def paste_back_frame(self, pred_frame, idx):\n"
        + BLEND_ANCHOR
    )
    source.write_text(original, encoding="utf-8")

    first_result = configure(source)
    first_text = source.read_text(encoding="utf-8")
    second_result = configure(source)

    assert first_result.startswith("configured; backup:")
    assert second_result == "already configured"
    assert PATCHED_IMPORT in first_text
    assert PATCHED_AVATAR in first_text
    assert PATCHED_BLEND in first_text
    assert source.with_suffix(".py.before-mouth-stabilizer").read_text(
        encoding="utf-8"
    ) == original


def test_configure_rejects_unknown_musetalk_source(tmp_path: Path) -> None:
    source = tmp_path / "musetalk_avatar.py"
    source.write_text("class MuseReal:\n    pass\n", encoding="utf-8")

    try:
        configure(source)
    except RuntimeError as exc:
        assert "Expected one BaseAvatar import" in str(exc)
    else:
        raise AssertionError("configure() should reject an unknown source layout")


def test_configure_upgrades_existing_stabilizer_patch(tmp_path: Path) -> None:
    source = tmp_path / "musetalk_avatar.py"
    original = (
        PATCHED_IMPORT
        + "\nclass MuseReal:\n"
        + "    def paste_back_frame(self, pred_frame, idx):\n"
        + LEGACY_PATCHED_BLEND
    )
    source.write_text(original, encoding="utf-8")

    result = configure(source)
    updated = source.read_text(encoding="utf-8")

    assert result == "upgraded existing configuration"
    assert PATCHED_BLEND in updated
    assert LEGACY_PATCHED_BLEND not in updated
