"""Install deterministic frame transitions for speech state changes."""

from __future__ import annotations

import argparse
import py_compile
import shutil
from pathlib import Path


STATE_ANCHOR = """        _last_speaking = False
        _transition_start = time.time()
"""
PATCHED_STATE = """        _last_speaking = False
        try:
            _frame_transition_frames = int(
                os.getenv("LIVETALKING_STATE_TRANSITION_FRAMES", "3")
            )
        except ValueError:
            _frame_transition_frames = 3
        _frame_transition_frames = max(0, min(6, _frame_transition_frames))
        _frame_transition_source = None
        _frame_transition_index = _frame_transition_frames
        _last_output_frame = None
        _transition_start = time.time()
"""
SPEAKING_ANCHOR = """            current_speaking = not (audio_frames[0].type!=0 and audio_frames[1].type!=0)
"""
PATCHED_SPEAKING = SPEAKING_ANCHOR + """            if (
                current_speaking != _last_speaking
                and _last_output_frame is not None
                and _frame_transition_frames > 0
            ):
                _frame_transition_source = _last_output_frame.copy()
                _frame_transition_index = 0
"""
OUTPUT_ANCHOR = """            cv2.putText(combine_frame, "LiveTalking", (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (128,128,128), 1)
"""
PATCHED_OUTPUT = """            if (
                _frame_transition_source is not None
                and _frame_transition_index < _frame_transition_frames
            ):
                alpha = (
                    (_frame_transition_index + 1)
                    / _frame_transition_frames
                )
                combine_frame = cv2.addWeighted(
                    _frame_transition_source,
                    1.0 - alpha,
                    combine_frame,
                    alpha,
                    0.0,
                )
                _frame_transition_index += 1
                if _frame_transition_index >= _frame_transition_frames:
                    _frame_transition_source = None
            _last_output_frame = combine_frame.copy()

""" + OUTPUT_ANCHOR


def _replace_once(text: str, old: str, new: str, description: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one {description}, found {count}")
    return text.replace(old, new, 1)


def configure(source: Path) -> str:
    text = source.read_text(encoding="utf-8")
    if (
        PATCHED_STATE in text
        and PATCHED_SPEAKING in text
        and PATCHED_OUTPUT in text
    ):
        return "already configured"

    updated = text
    if PATCHED_STATE not in updated:
        updated = _replace_once(
            updated,
            STATE_ANCHOR,
            PATCHED_STATE,
            "frame transition state",
        )
    if PATCHED_SPEAKING not in updated:
        updated = _replace_once(
            updated,
            SPEAKING_ANCHOR,
            PATCHED_SPEAKING,
            "speaking state calculation",
        )
    if PATCHED_OUTPUT not in updated:
        updated = _replace_once(
            updated,
            OUTPUT_ANCHOR,
            PATCHED_OUTPUT,
            "video output hook",
        )

    backup = source.with_suffix(source.suffix + ".before-frame-transitions")
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
        / "base_avatar.py"
    )
    if not source.is_file():
        raise FileNotFoundError(f"LiveTalking base avatar not found: {source}")
    print(f"{source}: {configure(source)}")


if __name__ == "__main__":
    main()
