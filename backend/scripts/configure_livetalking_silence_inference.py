"""Add optional MuseTalk inference for silent LiveTalking video frames."""

from __future__ import annotations

import argparse
import py_compile
import shutil
from pathlib import Path


ENV_NAME = "LIVETALKING_INFER_SILENCE"

INIT_ANCHOR = """        self.batch_size = opt.batch_size
        self.res_frame_queue = Queue(self.batch_size*2)
"""

PATCHED_INIT = f'''        self.batch_size = opt.batch_size
        self.infer_silence = os.getenv("{ENV_NAME}", "0").strip().lower() in {{
            "1", "true", "yes", "on"
        }}
        logger.info("MuseTalk silence inference: %s", self.infer_silence)
        self.res_frame_queue = Queue(self.batch_size*2)
'''

SILENCE_CONDITION = "            if is_all_silence:"
PATCHED_SILENCE_CONDITION = (
    "            if is_all_silence and not self.infer_silence:"
)

IDLE_FRAME_LINE = "                    target_frame = self.frame_list_cycle[idx]"
PATCHED_IDLE_FRAME = '''                    if self.infer_silence and res_frame is not None:
                        try:
                            target_frame = self.paste_back_frame(res_frame, idx)
                        except Exception as e:
                            logger.warning(f"silent paste_back_frame error: {e}")
                            target_frame = self.frame_list_cycle[idx]
                    else:
                        target_frame = self.frame_list_cycle[idx]'''


def _replace_once(text: str, old: str, new: str, description: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one {description}, found {count}")
    return text.replace(old, new, 1)


def configure(source: Path) -> str:
    text = source.read_text(encoding="utf-8")

    if ENV_NAME in text:
        return "already configured"

    updated = _replace_once(
        text,
        INIT_ANCHOR,
        PATCHED_INIT,
        "BaseAvatar initialization block",
    )
    updated = _replace_once(
        updated,
        SILENCE_CONDITION,
        PATCHED_SILENCE_CONDITION,
        "silence inference condition",
    )
    updated = _replace_once(
        updated,
        IDLE_FRAME_LINE,
        PATCHED_IDLE_FRAME,
        "idle frame output line",
    )

    backup = source.with_suffix(source.suffix + ".before-silence-inference")
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
        description="Allow LiveTalking to run MuseTalk inference during silence."
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
    source = args.livetalking_dir.expanduser().resolve() / "avatars" / "base_avatar.py"
    if not source.is_file():
        raise FileNotFoundError(f"LiveTalking avatar module not found: {source}")

    result = configure(source)
    print(f"{source}: {result}")
    print(f"Set {ENV_NAME}=1 before starting LiveTalking to enable it.")


if __name__ == "__main__":
    main()
