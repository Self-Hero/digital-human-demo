"""Add periodic WebRTC video keyframes to improve packet-loss recovery."""

from __future__ import annotations

import argparse
import py_compile
import shutil
from pathlib import Path


IMPORT_ANCHOR = """import json
import asyncio
"""
PATCHED_IMPORT = """import json
import asyncio
import os
"""
TRACK_ANCHOR = """        pc.addTrack(player.audio)
        pc.addTrack(player.video)

        # """
PATCHED_TRACK = '''        pc.addTrack(player.audio)
        video_sender = pc.addTrack(player.video)

        keyframe_interval = float(
            os.getenv("LIVETALKING_VIDEO_KEYFRAME_INTERVAL", "2.0")
        )
        if keyframe_interval > 0:
            async def request_periodic_keyframes():
                while pc.connectionState not in ("closed", "failed"):
                    await asyncio.sleep(keyframe_interval)
                    if pc.connectionState == "connected":
                        video_sender._send_keyframe()

            asyncio.create_task(request_periodic_keyframes())
            logger.info(
                "WebRTC periodic video keyframes: interval=%.1fs",
                keyframe_interval,
            )

        # '''


def configure(source: Path) -> str:
    text = source.read_text(encoding="utf-8")
    if PATCHED_TRACK in text:
        return "already configured"
    if TRACK_ANCHOR not in text:
        raise RuntimeError(
            f"Could not find WebRTC track anchors in {source}. "
            "The pinned LiveTalking source may have changed."
        )

    backup = source.with_suffix(source.suffix + ".before-keyframe-config")
    if not backup.exists():
        shutil.copy2(source, backup)

    updated = text
    if "import os\n" not in updated:
        if IMPORT_ANCHOR not in updated:
            raise RuntimeError(f"Could not find import anchors in {source}")
        updated = updated.replace(IMPORT_ANCHOR, PATCHED_IMPORT, 1)
    updated = updated.replace(TRACK_ANCHOR, PATCHED_TRACK, 1)
    source.write_text(updated, encoding="utf-8")
    try:
        py_compile.compile(str(source), doraise=True)
    except Exception:
        source.write_text(text, encoding="utf-8")
        raise
    return f"configured; backup: {backup}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Configure periodic LiveTalking WebRTC video keyframes."
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
        args.livetalking_dir.expanduser().resolve() / "server" / "rtc_manager.py"
    )
    if not source.is_file():
        raise FileNotFoundError(f"LiveTalking RTC manager not found: {source}")
    print(f"{source}: {configure(source)}")


if __name__ == "__main__":
    main()
