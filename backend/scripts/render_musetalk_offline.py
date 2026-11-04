"""Render an offline lip-synced MP4 with an existing LiveTalking avatar."""

from __future__ import annotations

import argparse
import math
import os
import pickle
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import soundfile as sf
import torch


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--livetalking-dir", type=Path, default=Path("/data/LiveTalking"))
    parser.add_argument("--avatar-id", required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fps", type=int, default=25)
    parser.add_argument("--batch-size", type=int, default=8)
    return parser.parse_args()


def load_images(directory: Path) -> list[np.ndarray]:
    files = sorted(
        (path for path in directory.iterdir() if path.suffix.lower() in {".jpg", ".jpeg", ".png"}),
        key=lambda path: int(path.stem),
    )
    images = [cv2.imread(str(path)) for path in files]
    if not images or any(image is None for image in images):
        raise RuntimeError(f"Could not load avatar images from {directory}")
    return images


def mirror_index(length: int, index: int) -> int:
    period = max(1, 2 * length - 2)
    position = index % period
    return position if position < length else period - position


def blend_face_clipped(
    image: np.ndarray,
    face: np.ndarray,
    face_box,
    mask_array: np.ndarray,
    crop_box,
) -> np.ndarray:
    """Blend a generated face when preprocessing boxes cross frame edges."""
    height, width = image.shape[:2]
    face_x1, face_y1, face_x2, face_y2 = (int(value) for value in face_box)
    crop_x1, crop_y1, crop_x2, crop_y2 = (int(value) for value in crop_box)
    crop_width = crop_x2 - crop_x1
    crop_height = crop_y2 - crop_y1
    if crop_width <= 0 or crop_height <= 0:
        return image

    clipped_crop_x1 = max(0, crop_x1)
    clipped_crop_y1 = max(0, crop_y1)
    clipped_crop_x2 = min(width, crop_x2)
    clipped_crop_y2 = min(height, crop_y2)
    if clipped_crop_x1 >= clipped_crop_x2 or clipped_crop_y1 >= clipped_crop_y2:
        return image

    if mask_array.shape[:2] != (crop_height, crop_width):
        mask_array = cv2.resize(mask_array, (crop_width, crop_height))
    mask_x1 = clipped_crop_x1 - crop_x1
    mask_y1 = clipped_crop_y1 - crop_y1
    mask_x2 = mask_x1 + clipped_crop_x2 - clipped_crop_x1
    mask_y2 = mask_y1 + clipped_crop_y2 - clipped_crop_y1
    clipped_mask = mask_array[mask_y1:mask_y2, mask_x1:mask_x2]

    region = image[
        clipped_crop_y1:clipped_crop_y2,
        clipped_crop_x1:clipped_crop_x2,
    ].copy()
    insert_x1 = max(clipped_crop_x1, face_x1)
    insert_y1 = max(clipped_crop_y1, face_y1)
    insert_x2 = min(clipped_crop_x2, face_x2)
    insert_y2 = min(clipped_crop_y2, face_y2)
    if insert_x1 < insert_x2 and insert_y1 < insert_y2:
        source_x1 = insert_x1 - face_x1
        source_y1 = insert_y1 - face_y1
        source_x2 = source_x1 + insert_x2 - insert_x1
        source_y2 = source_y1 + insert_y2 - insert_y1
        region[
            insert_y1 - clipped_crop_y1:insert_y2 - clipped_crop_y1,
            insert_x1 - clipped_crop_x1:insert_x2 - clipped_crop_x1,
        ] = face[source_y1:source_y2, source_x1:source_x2]

    if clipped_mask.ndim == 3:
        clipped_mask = cv2.cvtColor(clipped_mask, cv2.COLOR_BGR2GRAY)
    weights = clipped_mask.astype(np.float32) / 255.0
    if weights.shape != region.shape[:2]:
        weights = cv2.resize(weights, (region.shape[1], region.shape[0]))
    background = image[
        clipped_crop_y1:clipped_crop_y2,
        clipped_crop_x1:clipped_crop_x2,
    ]
    image[
        clipped_crop_y1:clipped_crop_y2,
        clipped_crop_x1:clipped_crop_x2,
    ] = cv2.blendLinear(region, background, weights, 1.0 - weights)
    return image


def main() -> None:
    args = parse_args()
    root = args.livetalking_dir.expanduser().resolve()
    avatar_dir = root / "data" / "avatars" / args.avatar_id
    audio_path = args.audio.expanduser().resolve()
    output_path = args.output.expanduser().resolve()
    required = [
        avatar_dir / "full_imgs",
        avatar_dir / "mask",
        avatar_dir / "coords.pkl",
        avatar_dir / "mask_coords.pkl",
        avatar_dir / "latents.pt",
        audio_path,
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing input: " + ", ".join(missing))
    if args.fps <= 0 or args.batch_size <= 0:
        raise ValueError("fps and batch-size must be positive")

    os.chdir(root)
    sys.path.insert(0, str(root))
    from avatars.mouth_stabilizer import MouthTemporalStabilizer
    from avatars.musetalk_avatar import load_model

    audio, sample_rate = sf.read(str(audio_path), dtype="float32", always_2d=False)
    if sample_rate != 16000:
        raise ValueError(f"Audio must be 16 kHz; got {sample_rate} Hz")
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    frame_count = math.ceil(len(audio) / sample_rate * args.fps)

    frames = load_images(avatar_dir / "full_imgs")
    masks = load_images(avatar_dir / "mask")
    with (avatar_dir / "coords.pkl").open("rb") as handle:
        coords = pickle.load(handle)
    with (avatar_dir / "mask_coords.pkl").open("rb") as handle:
        mask_coords = pickle.load(handle)
    latents = torch.load(avatar_dir / "latents.pt", map_location="cpu")
    length = len(frames)
    if not (length == len(masks) == len(coords) == len(mask_coords) == len(latents)):
        raise RuntimeError("Avatar assets have inconsistent frame counts")

    vae, unet, pe, timesteps, audio_processor = load_model()
    audio_features = audio_processor.audio2feat(audio)
    chunks = [
        audio_processor.get_sliced_feature(audio_features, index, fps=args.fps)[0]
        for index in range(frame_count)
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    width, height = frames[0].shape[1], frames[0].shape[0]
    ffmpeg = subprocess.Popen(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}",
            "-r", str(args.fps), "-i", "-", "-i", str(audio_path),
            "-c:v", "libx264", "-preset", "medium", "-crf", "16",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart", str(output_path),
        ],
        stdin=subprocess.PIPE,
    )
    if ffmpeg.stdin is None:
        raise RuntimeError("Could not open FFmpeg input pipe")

    stabilizer = MouthTemporalStabilizer()
    try:
        for start in range(0, frame_count, args.batch_size):
            stop = min(frame_count, start + args.batch_size)
            actual = stop - start
            batch_chunks = chunks[start:stop]
            batch_indices = [mirror_index(length, index) for index in range(start, stop)]
            while len(batch_chunks) < args.batch_size:
                batch_chunks.append(batch_chunks[-1])
                batch_indices.append(batch_indices[-1])

            latent_batch = torch.cat([latents[index] for index in batch_indices], dim=0)
            feature_batch = torch.from_numpy(np.stack(batch_chunks)).to(
                device=unet.device, dtype=unet.model.dtype
            )
            latent_batch = latent_batch.to(device=unet.device, dtype=unet.model.dtype)
            with torch.inference_mode():
                generated = vae.decode_latents(
                    unet.model(
                        latent_batch,
                        timesteps,
                        encoder_hidden_states=pe(feature_batch),
                    ).sample
                )

            for offset in range(actual):
                index = batch_indices[offset]
                original = frames[index].copy()
                x1, y1, x2, y2 = coords[index]
                face = cv2.resize(
                    generated[offset].astype(np.uint8),
                    (x2 - x1, y2 - y1),
                )
                combined = blend_face_clipped(
                    original,
                    face,
                    coords[index],
                    masks[index],
                    mask_coords[index],
                )
                combined = stabilizer.apply(combined, coords[index], original)
                ffmpeg.stdin.write(combined.tobytes())
            print(f"Rendered {stop}/{frame_count} frames", flush=True)
    finally:
        ffmpeg.stdin.close()
        return_code = ffmpeg.wait()
    if return_code != 0:
        raise RuntimeError(f"FFmpeg exited with status {return_code}")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    main()
