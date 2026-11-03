"""Register the maintained PCM streaming endpoint in LiveTalking."""

from __future__ import annotations

import argparse
import py_compile
import shutil
from pathlib import Path


IMPORT_ANCHOR = "from server.avatar_routes import setup_avatar_routes\n"
PATCHED_IMPORT = (
    "from server.avatar_routes import setup_avatar_routes\n"
    "from server.pcm_stream import pcm_stream\n"
)
ROUTE_ANCHOR = '    app.router.add_post("/humanaudio", humanaudio)\n'
PATCHED_ROUTE = (
    '    app.router.add_post("/humanaudio", humanaudio)\n'
    '    app.router.add_get("/humanpcm", pcm_stream)\n'
)


def configure(source: Path) -> str:
    text = source.read_text(encoding="utf-8")

    if PATCHED_IMPORT in text and PATCHED_ROUTE in text:
        return "already configured"
    if IMPORT_ANCHOR not in text or ROUTE_ANCHOR not in text:
        raise RuntimeError(
            f"Could not find the expected route anchors in {source}. "
            "The pinned LiveTalking source may have changed."
        )

    backup = source.with_suffix(source.suffix + ".before-pcm-stream")
    if not backup.exists():
        shutil.copy2(source, backup)

    updated = text.replace(IMPORT_ANCHOR, PATCHED_IMPORT, 1)
    updated = updated.replace(ROUTE_ANCHOR, PATCHED_ROUTE, 1)
    source.write_text(updated, encoding="utf-8")
    try:
        py_compile.compile(str(source), doraise=True)
    except Exception:
        source.write_text(text, encoding="utf-8")
        raise
    return f"configured; backup: {backup}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Register the /humanpcm WebSocket endpoint in LiveTalking."
    )
    parser.add_argument(
        "--livetalking-dir",
        type=Path,
        default=Path("/data/LiveTalking"),
        help="LiveTalking checkout (default: /data/LiveTalking)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source = args.livetalking_dir.expanduser().resolve() / "server" / "routes.py"
    if not source.is_file():
        raise FileNotFoundError(f"LiveTalking routes module not found: {source}")
    print(f"{source}: {configure(source)}")


if __name__ == "__main__":
    main()
