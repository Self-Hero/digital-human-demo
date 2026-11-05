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
SYNC_INFERENCE = """        pred = self.vae.decode_latents(pred_latents)
        pred = self.gfpgan_enhancer.enhance_batch(pred)
        return pred
"""
PATCHED_INFERENCE = """        pred = self.vae.decode_latents(pred_latents)
        pred = self.gfpgan_enhancer.enhance_batch_async(pred)
        return pred
"""
PASTE_ANCHOR = """    def paste_back_frame(self,pred_frame,idx:int):
        bbox = self.coord_list_cycle[idx]
"""
PATCHED_PASTE = """    def paste_back_frame(self,pred_frame,idx:int):
        pred_frame = self.gfpgan_enhancer.resolve_frame(pred_frame)
        bbox = self.coord_list_cycle[idx]
"""
APP_IMPORT_ANCHOR = "from utils.logger import logger\n"
PATCHED_APP_IMPORT = (
    APP_IMPORT_ANCHOR
    + "from avatars.gfpgan_enhancer import preload_realtime_gfpgan\n"
)
APP_WARMUP_ANCHOR = "        warm_up(opt.batch_size,model)"
PATCHED_APP_WARMUP = (
    APP_WARMUP_ANCHOR
    + "\n        preload_realtime_gfpgan()"
)


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
        and PATCHED_PASTE in text
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
        if SYNC_INFERENCE in updated:
            updated = _replace_once(
                updated, SYNC_INFERENCE, PATCHED_INFERENCE, "synchronous GFPGAN hook"
            )
        else:
            updated = _replace_once(
                updated, INFERENCE_ANCHOR, PATCHED_INFERENCE, "MuseTalk batch decode"
            )
    if PATCHED_PASTE not in updated:
        updated = _replace_once(
            updated, PASTE_ANCHOR, PATCHED_PASTE, "MuseTalk paste-back hook"
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


def configure_app(source: Path) -> str:
    text = source.read_text(encoding="utf-8")
    if PATCHED_APP_IMPORT in text and PATCHED_APP_WARMUP in text:
        return "already configured"

    updated = text
    if PATCHED_APP_IMPORT not in updated:
        updated = _replace_once(
            updated, APP_IMPORT_ANCHOR, PATCHED_APP_IMPORT, "app GFPGAN import"
        )
    if PATCHED_APP_WARMUP not in updated:
        updated = _replace_once(
            updated, APP_WARMUP_ANCHOR, PATCHED_APP_WARMUP, "MuseTalk startup warmup"
        )

    backup = source.with_suffix(source.suffix + ".before-gfpgan-preload")
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
    root = args.livetalking_dir.expanduser().resolve()
    avatar_source = root / "avatars" / "musetalk_avatar.py"
    app_source = root / "app.py"
    if not avatar_source.is_file():
        raise FileNotFoundError(
            f"LiveTalking MuseTalk avatar not found: {avatar_source}"
        )
    if not app_source.is_file():
        raise FileNotFoundError(f"LiveTalking app not found: {app_source}")
    print(f"{avatar_source}: {configure(avatar_source)}")
    print(f"{app_source}: {configure_app(app_source)}")


if __name__ == "__main__":
    main()
