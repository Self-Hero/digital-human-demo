"""Configure the resolution of frames sent by LiveTalking over WebRTC."""

from __future__ import annotations

import argparse
import py_compile
import shutil
from pathlib import Path


IMPORT_ANCHOR = "import numpy as np\n"
IMPORT_BLOCK = "import numpy as np\nimport cv2\nimport os\n"

ORIGINAL_METHOD = '''    def push_video(self, frame):
        from av import VideoFrame
        new_frame = VideoFrame.from_ndarray(frame, format="bgr24")
        self.__video._queue.put((new_frame, None))
'''

PATCHED_METHOD = '''    def push_video(self, frame):
        from av import VideoFrame

        target_width = int(os.getenv("LIVETALKING_VIDEO_WIDTH", "720"))
        target_height = int(os.getenv("LIVETALKING_VIDEO_HEIGHT", "1280"))
        if target_width <= 0 or target_height <= 0:
            raise ValueError("LiveTalking video dimensions must be positive")

        frame_height, frame_width = frame.shape[:2]
        if (frame_width, frame_height) != (target_width, target_height):
            interpolation = (
                cv2.INTER_AREA
                if target_width <= frame_width and target_height <= frame_height
                else cv2.INTER_LINEAR
            )
            frame = cv2.resize(
                frame,
                (target_width, target_height),
                interpolation=interpolation,
            )

        new_frame = VideoFrame.from_ndarray(frame, format="bgr24")
        self.__video._queue.put((new_frame, None))
'''


def configure(source: Path) -> str:
    text = source.read_text(encoding="utf-8")

    if PATCHED_METHOD in text:
        return "already configured"
    if ORIGINAL_METHOD not in text:
        raise RuntimeError(
            "Could not find HumanPlayer.push_video() in "
            f"{source}. The LiveTalking source may have changed."
        )
    if IMPORT_ANCHOR not in text:
        raise RuntimeError(f"Could not find the NumPy import in {source}")

    backup = source.with_suffix(source.suffix + ".before-720p")
    if not backup.exists():
        shutil.copy2(source, backup)

    updated = text.replace(IMPORT_ANCHOR, IMPORT_BLOCK, 1)
    updated = updated.replace(ORIGINAL_METHOD, PATCHED_METHOD, 1)
    source.write_text(updated, encoding="utf-8")

    try:
        py_compile.compile(str(source), doraise=True)
    except Exception:
        source.write_text(text, encoding="utf-8")
        raise

    return f"configured; backup: {backup}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resize LiveTalking WebRTC video frames to 720x1280 by default."
    )
    parser.add_argument(
        "--livetalking-dir",
        type=Path,
        default=Path("/root/LiveTalking"),
        help="LiveTalking checkout (default: /root/LiveTalking)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source = args.livetalking_dir.expanduser().resolve() / "server" / "webrtc.py"
    if not source.is_file():
        raise FileNotFoundError(f"LiveTalking WebRTC module not found: {source}")
    result = configure(source)
    print(f"{source}: {result}")
    print("WebRTC output: 720x1280 (override with LIVETALKING_VIDEO_WIDTH/HEIGHT)")


if __name__ == "__main__":
    main()
