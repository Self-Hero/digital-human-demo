"""Close the lips in a source video with LivePortrait's silence mode."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from dataclasses import fields
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--liveportrait-dir", type=Path, default=Path("/data/LivePortrait"))
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device-id", type=int, default=0)
    parser.add_argument("--crop-scale", type=float, default=2.3)
    parser.add_argument("--source-max-dim", type=int, default=1920)
    return parser.parse_args()


def select_fields(config_type: type, values: dict[str, object]) -> dict[str, object]:
    names = {field.name for field in fields(config_type)}
    return {key: value for key, value in values.items() if key in names}


def main() -> None:
    args = parse_args()
    root = args.liveportrait_dir.expanduser().resolve()
    input_path = args.input.expanduser().resolve()
    output_path = args.output.expanduser().resolve()
    if not (root / "src" / "gradio_pipeline.py").is_file():
        raise FileNotFoundError(f"LivePortrait is missing at {root}")
    if not input_path.is_file():
        raise FileNotFoundError(f"Input video is missing: {input_path}")
    if args.source_max_dim <= 0 or args.crop_scale <= 0:
        raise ValueError("source-max-dim and crop-scale must be positive")

    os.chdir(root)
    sys.path.insert(0, str(root))
    from src.config.argument_config import ArgumentConfig
    from src.config.crop_config import CropConfig
    from src.config.inference_config import InferenceConfig
    from src.gradio_pipeline import GradioPipeline

    work_dir = output_path.parent / f".{output_path.stem}-liveportrait"
    work_dir.mkdir(parents=True, exist_ok=True)
    values: dict[str, object] = {
        "output_dir": str(work_dir),
        "device_id": args.device_id,
        "scale": args.crop_scale,
        "source_max_dim": args.source_max_dim,
        "flag_use_half_precision": True,
        "flag_force_cpu": False,
        "flag_do_crop": True,
        "flag_pasteback": True,
        "flag_stitching": True,
    }
    argument_cfg = ArgumentConfig(**select_fields(ArgumentConfig, values))
    inference_cfg = InferenceConfig(**select_fields(InferenceConfig, values))
    crop_cfg = CropConfig(**select_fields(CropConfig, values))
    pipeline = GradioPipeline(
        inference_cfg=inference_cfg,
        crop_cfg=crop_cfg,
        args=argument_cfg,
    )
    concat_path, result_path = pipeline.execute_video_retargeting(
        input_lip_ratio=0.0,
        input_video=str(input_path),
        retargeting_source_scale=args.crop_scale,
        driving_smooth_observation_variance_retargeting=3e-6,
        video_retargeting_silence=True,
        flag_do_crop_input_retargeting_video=True,
    )

    generated_path = Path(result_path).resolve()
    if not generated_path.is_file():
        raise RuntimeError(f"LivePortrait did not produce {generated_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(generated_path, output_path)
    concat = Path(concat_path)
    if concat.is_file():
        concat.unlink()
    print(f"Neutralized video: {output_path}")


if __name__ == "__main__":
    main()
