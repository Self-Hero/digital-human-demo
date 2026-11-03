"""Install the maintained temporal mouth stabilizer into MuseTalk."""

from __future__ import annotations

import argparse
import py_compile
import shutil
from pathlib import Path


IMPORT_ANCHOR = "from avatars.base_avatar import BaseAvatar\n"
PATCHED_IMPORT = (
    "from avatars.base_avatar import BaseAvatar\n"
    "from avatars.mouth_stabilizer import MouthTemporalStabilizer\n"
)
AVATAR_ANCHOR = """        self.frame_list_cycle,self.mask_list_cycle,self.coord_list_cycle,self.mask_coords_list_cycle, self.input_latent_list_cycle = avatar

        self.asr = WhisperASR(opt,self,self.audio_processor)
"""
PATCHED_AVATAR = """        self.frame_list_cycle,self.mask_list_cycle,self.coord_list_cycle,self.mask_coords_list_cycle, self.input_latent_list_cycle = avatar
        self.mouth_stabilizer = MouthTemporalStabilizer()

        self.asr = WhisperASR(opt,self,self.audio_processor)
"""
BLEND_ANCHOR = """        combine_frame = get_image_blending(ori_frame,res_frame,bbox,mask,mask_crop_box)
        return combine_frame
"""
PATCHED_BLEND = """        combine_frame = get_image_blending(ori_frame,res_frame,bbox,mask,mask_crop_box)
        combine_frame = self.mouth_stabilizer.apply(combine_frame, bbox)
        return combine_frame
"""


def _replace_once(text: str, old: str, new: str, description: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one {description}, found {count}")
    return text.replace(old, new, 1)


def configure(source: Path) -> str:
    text = source.read_text(encoding="utf-8")
    if PATCHED_IMPORT in text and PATCHED_BLEND in text:
        return "already configured"

    updated = _replace_once(text, IMPORT_ANCHOR, PATCHED_IMPORT, "BaseAvatar import")
    updated = _replace_once(
        updated, AVATAR_ANCHOR, PATCHED_AVATAR, "MuseTalk avatar initialization"
    )
    updated = _replace_once(
        updated, BLEND_ANCHOR, PATCHED_BLEND, "MuseTalk frame blend"
    )

    backup = source.with_suffix(source.suffix + ".before-mouth-stabilizer")
    if not backup.exists():
        shutil.copy2(source, backup)
    source.write_text(updated, encoding="utf-8")
    try:
        py_compile.compile(str(source), doraise=True)
    except Exception:
        source.write_text(text, encoding="utf-8")
        raise
    return f"configured; backup: {backup}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enable temporal mouth stabilization in LiveTalking MuseTalk."
    )
    parser.add_argument(
        "--livetalking-dir",
        type=Path,
        default=Path("/data/LiveTalking"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
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
