"""Tune MuseTalk blend masks without regenerating avatar latents.

The original masks are copied to ``mask.original`` once. Every subsequent run
starts from that backup, so trying different values does not compound the
previous erosion or opacity reduction.
"""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

import cv2
import numpy as np


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}


def mask_files(directory: Path) -> list[Path]:
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )


def write_image_atomic(path: Path, image: np.ndarray) -> None:
    temporary = path.with_name(f".{path.stem}.tmp{path.suffix}")
    if not cv2.imwrite(str(temporary), image):
        raise RuntimeError(f"Failed to write mask: {temporary}")
    os.replace(temporary, path)


def restore_masks(mask_dir: Path, backup_dir: Path) -> int:
    source_files = mask_files(backup_dir)
    if not source_files:
        raise RuntimeError(f"No mask images found in backup: {backup_dir}")

    for source in source_files:
        shutil.copy2(source, mask_dir / source.name)
    return len(source_files)


def tune_masks(
    avatar_dir: Path,
    *,
    erode_px: int,
    opacity: float,
    dry_run: bool = False,
) -> tuple[int, float, float]:
    mask_dir = avatar_dir / "mask"
    backup_dir = avatar_dir / "mask.original"

    if not mask_dir.is_dir():
        raise RuntimeError(f"MuseTalk mask directory does not exist: {mask_dir}")
    if not (avatar_dir / "full_imgs").is_dir():
        raise RuntimeError(f"MuseTalk full_imgs directory does not exist: {avatar_dir}")

    current_files = mask_files(mask_dir)
    if not current_files:
        raise RuntimeError(f"No mask images found: {mask_dir}")

    if not backup_dir.exists() and not dry_run:
        shutil.copytree(mask_dir, backup_dir)

    source_dir = backup_dir if backup_dir.is_dir() else mask_dir
    source_files = mask_files(source_dir)
    kernel = None
    if erode_px:
        size = erode_px * 2 + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))

    original_alpha = 0.0
    tuned_alpha = 0.0
    for source in source_files:
        mask = cv2.imread(str(source), cv2.IMREAD_GRAYSCALE)
        if mask is None:
            raise RuntimeError(f"Failed to read mask: {source}")

        tuned = cv2.erode(mask, kernel, iterations=1) if kernel is not None else mask
        tuned = np.clip(tuned.astype(np.float32) * opacity, 0, 255).astype(np.uint8)
        original_alpha += float(mask.mean())
        tuned_alpha += float(tuned.mean())

        if not dry_run:
            write_image_atomic(mask_dir / source.name, tuned)

    count = len(source_files)
    return count, original_alpha / count, tuned_alpha / count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Shrink and soften MuseTalk's generated-face blend region."
    )
    parser.add_argument("avatar_dir", type=Path, help="Avatar directory containing mask/")
    parser.add_argument(
        "--erode-px",
        type=int,
        default=3,
        help="Inward mask shrink in pixels (default: 3)",
    )
    parser.add_argument(
        "--opacity",
        type=float,
        default=0.92,
        help="Generated-face blend strength from 0 to 1 (default: 0.92)",
    )
    parser.add_argument(
        "--restore",
        action="store_true",
        help="Restore mask/ from mask.original and exit",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report without writing files")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    avatar_dir = args.avatar_dir.expanduser().resolve()
    mask_dir = avatar_dir / "mask"
    backup_dir = avatar_dir / "mask.original"

    if args.erode_px < 0:
        raise SystemExit("--erode-px must be zero or greater")
    if not 0 < args.opacity <= 1:
        raise SystemExit("--opacity must be greater than 0 and at most 1")

    if args.restore:
        if not backup_dir.is_dir():
            raise SystemExit(f"Backup does not exist: {backup_dir}")
        count = restore_masks(mask_dir, backup_dir)
        print(f"Restored {count} masks from {backup_dir}")
        return

    count, before, after = tune_masks(
        avatar_dir,
        erode_px=args.erode_px,
        opacity=args.opacity,
        dry_run=args.dry_run,
    )
    action = "Would tune" if args.dry_run else "Tuned"
    print(
        f"{action} {count} masks: mean alpha {before:.2f} -> {after:.2f}; "
        f"erode={args.erode_px}px opacity={args.opacity:.2f}"
    )
    if not args.dry_run:
        print(f"Original masks: {backup_dir}")


if __name__ == "__main__":
    main()
