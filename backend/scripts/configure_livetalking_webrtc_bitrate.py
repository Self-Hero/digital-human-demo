"""Configure adaptive WebRTC video bitrate limits in LiveTalking."""

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
LOGGER_ANCHOR = """from utils.logger import logger


"""
PATCHED_CONFIG = '''from utils.logger import logger


def _configure_video_bitrate():
    from aiortc.codecs import h264, vpx

    initial = int(os.getenv("LIVETALKING_VIDEO_BITRATE_INITIAL", "3000000"))
    minimum = int(os.getenv("LIVETALKING_VIDEO_BITRATE_MIN", "1000000"))
    maximum = int(os.getenv("LIVETALKING_VIDEO_BITRATE_MAX", "6000000"))
    if not 100000 <= minimum <= initial <= maximum:
        raise ValueError(
            "Expected video bitrate values to satisfy "
            "100000 <= min <= initial <= max"
        )

    for codec in (h264, vpx):
        codec.DEFAULT_BITRATE = initial
        codec.MIN_BITRATE = minimum
        codec.MAX_BITRATE = maximum
    logger.info(
        "WebRTC video bitrate: initial=%d min=%d max=%d bps",
        initial,
        minimum,
        maximum,
    )


_configure_video_bitrate()


'''


def configure(source: Path) -> str:
    text = source.read_text(encoding="utf-8")
    if PATCHED_CONFIG in text:
        return "already configured"
    if IMPORT_ANCHOR not in text or LOGGER_ANCHOR not in text:
        raise RuntimeError(
            f"Could not find WebRTC bitrate anchors in {source}. "
            "The pinned LiveTalking source may have changed."
        )

    backup = source.with_suffix(source.suffix + ".before-bitrate-config")
    if not backup.exists():
        shutil.copy2(source, backup)

    updated = text.replace(IMPORT_ANCHOR, PATCHED_IMPORT, 1)
    updated = updated.replace(LOGGER_ANCHOR, PATCHED_CONFIG, 1)
    source.write_text(updated, encoding="utf-8")
    try:
        py_compile.compile(str(source), doraise=True)
    except Exception:
        source.write_text(text, encoding="utf-8")
        raise
    return f"configured; backup: {backup}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Configure adaptive WebRTC video bitrate limits."
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
