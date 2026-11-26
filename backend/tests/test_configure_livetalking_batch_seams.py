from pathlib import Path

from scripts.configure_livetalking_batch_seams import (
    APPLY_ANCHOR,
    PASTE_ANCHOR,
    PATCHED_APPLY,
    PATCHED_PASTE,
    PATCHED_RETURN,
    RETURN_ANCHOR,
    configure,
)


def test_configure_batch_seams_is_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "musetalk_avatar.py"
    original = (
        "class MuseReal:\n"
        "    def inference_batch(self):\n"
        "        pred = []\n"
        + RETURN_ANCHOR
        + "\n"
        + PASTE_ANCHOR
        + "        pred_frame = self.gfpgan_enhancer.resolve_frame(pred_frame)\n"
        "        bbox = self.coord_list_cycle[idx]\n"
        "        combine_frame = None\n"
        + APPLY_ANCHOR
        + "        return combine_frame\n"
    )
    source.write_text(original, encoding="utf-8")

    first_result = configure(source)
    first_text = source.read_text(encoding="utf-8")
    second_result = configure(source)

    assert first_result.startswith("configured; backup:")
    assert second_result == "already configured"
    assert PATCHED_RETURN in first_text
    assert PATCHED_PASTE in first_text
    assert PATCHED_APPLY in first_text
    assert first_text.index("pred_frame, batch_position") < first_text.index(
        "resolve_frame(pred_frame)"
    )
    assert source.with_suffix(".py.before-batch-seams").read_text(
        encoding="utf-8"
    ) == original
