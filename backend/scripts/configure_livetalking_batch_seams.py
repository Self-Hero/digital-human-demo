"""Tag MuseTalk batch frames so mouth smoothing can bridge batch seams."""

from __future__ import annotations

import argparse
import py_compile
import shutil
from pathlib import Path


RETURN_ANCHOR = "        return pred\n"
PATCHED_RETURN = """        return [
            (frame, batch_position)
            for batch_position, frame in enumerate(pred)
        ]
"""
PASTE_ANCHOR = """    def paste_back_frame(self,pred_frame,idx:int):
"""
PATCHED_PASTE = """    def paste_back_frame(self,pred_frame,idx:int):
        pred_frame, batch_position = pred_frame
"""
APPLY_ANCHOR = """        combine_frame = self.mouth_stabilizer.apply(combine_frame, bbox, ori_frame)
"""
PATCHED_APPLY = """        combine_frame = self.mouth_stabilizer.apply(
            combine_frame,
            bbox,
            ori_frame,
            batch_position=batch_position,
        )
"""


def _replace_once(text: str, old: str, new: str, description: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one {description}, found {count}")
    return text.replace(old, new, 1)


def configure(source: Path) -> str:
    text = source.read_text(encoding="utf-8")
    if (
        PATCHED_RETURN in text
        and PATCHED_PASTE in text
        and PATCHED_APPLY in text
    ):
        return "already configured"

    updated = text
    if PATCHED_RETURN not in updated:
        updated = _replace_once(
            updated,
            RETURN_ANCHOR,
            PATCHED_RETURN,
            "MuseTalk inference return",
        )
    if PATCHED_PASTE not in updated:
        updated = _replace_once(
            updated,
            PASTE_ANCHOR,
            PATCHED_PASTE,
            "MuseTalk paste-back method",
        )
    if PATCHED_APPLY not in updated:
        updated = _replace_once(
            updated,
            APPLY_ANCHOR,
            PATCHED_APPLY,
            "mouth stabilizer call",
        )

    backup = source.with_suffix(source.suffix + ".before-batch-seams")
    if not backup.exists():
        shutil.copy2(source, backup)
    source.write_text(updated, encoding="utf-8")
    try:
        py_compile.compile(str(source), doraise=True)
    except Exception:
        source.write_text(text, encoding="utf-8")
        raise
    return f"configured; backup: {backup}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--livetalking-dir", type=Path, default=Path("/data/LiveTalking")
    )
    args = parser.parse_args()
    source = (
        args.livetalking_dir.expanduser().resolve()
        / "avatars"
        / "musetalk_avatar.py"
    )
    if not source.is_file():
        raise FileNotFoundError(f"LiveTalking MuseTalk avatar not found: {source}")
    print(f"{source}: {configure(source)}")


if __name__ == "__main__":
    main()
