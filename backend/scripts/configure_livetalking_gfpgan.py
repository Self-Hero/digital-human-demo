"""Install the optional batched GFPGAN hook into LiveTalking MuseTalk."""

from __future__ import annotations

import argparse
import py_compile
import shutil
from pathlib import Path


IMPORT_ANCHOR = "from avatars.mouth_stabilizer import MouthTemporalStabilizer\n"
PATCHED_IMPORT = (
    IMPORT_ANCHOR
    + "from avatars.gfpgan_enhancer import RealtimeGFPGANEnhancer\n"
)
AVATAR_ANCHOR = "        self.mouth_stabilizer = MouthTemporalStabilizer()\n"
PATCHED_AVATAR = (
    AVATAR_ANCHOR
    + "        self.gfpgan_enhancer = RealtimeGFPGANEnhancer()\n"
)
INFERENCE_ANCHOR = """        pred = self.vae.decode_latents(pred_latents)
        return pred
"""
PATCHED_INFERENCE = """        pred = self.vae.decode_latents(pred_latents)
        pred = self.gfpgan_enhancer.enhance_batch(pred)
        return pred
"""


def _replace_once(text: str, old: str, new: str, description: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one {description}, found {count}")
    return text.replace(old, new, 1)


def configure(source: Path) -> str:
    text = source.read_text(encoding="utf-8")
    if (
        PATCHED_IMPORT in text
        and PATCHED_AVATAR in text
        and PATCHED_INFERENCE in text
    ):
        return "already configured"

    updated = text
    if PATCHED_IMPORT not in updated:
        updated = _replace_once(
            updated, IMPORT_ANCHOR, PATCHED_IMPORT, "mouth stabilizer import"
        )
    if PATCHED_AVATAR not in updated:
        updated = _replace_once(
            updated, AVATAR_ANCHOR, PATCHED_AVATAR, "mouth stabilizer initialization"
        )
    if PATCHED_INFERENCE not in updated:
        updated = _replace_once(
            updated, INFERENCE_ANCHOR, PATCHED_INFERENCE, "MuseTalk batch decode"
        )

    backup = source.with_suffix(source.suffix + ".before-gfpgan")
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
    parser.add_argument("--livetalking-dir", type=Path, default=Path("/data/LiveTalking"))
    args = parser.parse_args()
    source = args.livetalking_dir.expanduser().resolve() / "avatars" / "musetalk_avatar.py"
    if not source.is_file():
        raise FileNotFoundError(f"LiveTalking MuseTalk avatar not found: {source}")
    print(f"{source}: {configure(source)}")


if __name__ == "__main__":
    main()
