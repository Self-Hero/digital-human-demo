"""Blend face restoration with MuseTalk output and suppress low-motion flicker."""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--restored", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--blend", type=float, default=0.68)
    parser.add_argument("--temporal-strength", type=float, default=0.12)
    parser.add_argument("--motion-threshold", type=float, default=5.0)
    return parser.parse_args()


def video_properties(capture: cv2.VideoCapture) -> tuple[float, int, int]:
    fps = capture.get(cv2.CAP_PROP_FPS)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if fps <= 0 or width <= 0 or height <= 0:
        raise RuntimeError("Could not read video properties")
    return fps, width, height


def main() -> None:
    args = parse_args()
    if not 0 <= args.blend <= 1:
        raise ValueError("blend must be between 0 and 1")
    if not 0 <= args.temporal_strength <= 1:
        raise ValueError("temporal-strength must be between 0 and 1")
    if args.motion_threshold < 0:
        raise ValueError("motion-threshold must be non-negative")

    source_path = args.source.expanduser().resolve()
    restored_path = args.restored.expanduser().resolve()
    output_path = args.output.expanduser().resolve()
    for path in (source_path, restored_path):
        if not path.is_file():
            raise FileNotFoundError(path)

    source_capture = cv2.VideoCapture(str(source_path))
    restored_capture = cv2.VideoCapture(str(restored_path))
    try:
        fps, width, height = video_properties(source_capture)
        restored_fps, restored_width, restored_height = video_properties(restored_capture)
        if (width, height) != (restored_width, restored_height):
            raise ValueError("Source and restored videos have different dimensions")
        if abs(fps - restored_fps) > 0.1:
            raise ValueError("Source and restored videos have different frame rates")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="face-blend-") as temp_dir:
            silent_path = Path(temp_dir) / "silent.mp4"
            writer = cv2.VideoWriter(
                str(silent_path),
                cv2.VideoWriter_fourcc(*"mp4v"),
                fps,
                (width, height),
            )
            if not writer.isOpened():
                raise RuntimeError("Could not create temporary output video")

            previous_source_gray: np.ndarray | None = None
            previous_output: np.ndarray | None = None
            frame_count = 0
            try:
                while True:
                    source_ok, source = source_capture.read()
                    restored_ok, restored = restored_capture.read()
                    if source_ok != restored_ok:
                        raise RuntimeError("Source and restored videos have different frame counts")
                    if not source_ok:
                        break

                    current = cv2.addWeighted(
                        restored,
                        args.blend,
                        source,
                        1.0 - args.blend,
                        0,
                    )
                    source_gray = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
                    if previous_source_gray is not None and previous_output is not None:
                        motion = cv2.absdiff(source_gray, previous_source_gray)
                        low_motion = (motion < args.motion_threshold).astype(np.float32)
                        restoration_delta = np.mean(
                            cv2.absdiff(restored, source), axis=2
                        )
                        changed = (restoration_delta > 2.0).astype(np.float32)
                        mask = cv2.GaussianBlur(low_motion * changed, (0, 0), 1.2)
                        alpha = (mask * args.temporal_strength)[..., None]
                        current = np.clip(
                            current.astype(np.float32) * (1.0 - alpha)
                            + previous_output.astype(np.float32) * alpha,
                            0,
                            255,
                        ).astype(np.uint8)

                    writer.write(current)
                    previous_source_gray = source_gray
                    previous_output = current
                    frame_count += 1
            finally:
                writer.release()

            if frame_count == 0:
                raise RuntimeError("No frames were processed")
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(silent_path), "-i", str(source_path),
                    "-map", "0:v:0", "-map", "1:a:0?", "-c:v", "libx264",
                    "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", "-shortest",
                    "-movflags", "+faststart", str(output_path),
                ],
                check=True,
            )
    finally:
        source_capture.release()
        restored_capture.release()
    print(f"Final video: {output_path}")


if __name__ == "__main__":
    main()
