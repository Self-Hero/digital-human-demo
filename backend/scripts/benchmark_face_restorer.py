"""Benchmark the restoration network without detection, alignment, or file I/O."""

from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

import torch


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=("gfpgan", "codeformer"), required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--batches", type=int, nargs="+", default=(1, 2, 4, 8))
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--amp", action="store_true")
    parser.add_argument("--fidelity", type=float, default=0.7)
    return parser.parse_args()


def load_gfpgan(args: argparse.Namespace, device: torch.device):
    sys.path.insert(0, str(args.repo.resolve()))
    from gfpgan import GFPGANer

    restorer = GFPGANer(
        model_path=str(args.checkpoint.resolve()),
        upscale=1,
        arch="clean",
        channel_multiplier=2,
        bg_upsampler=None,
        device=device,
    )

    def infer(tensor: torch.Tensor) -> torch.Tensor:
        return restorer.gfpgan(
            tensor,
            return_rgb=False,
            weight=0.5,
        )[0]

    return infer


def load_codeformer(args: argparse.Namespace, device: torch.device):
    sys.path.insert(0, str(args.repo.resolve()))
    from basicsr.archs.codeformer_arch import CodeFormer

    network = CodeFormer(
        dim_embd=512,
        codebook_size=1024,
        n_head=8,
        n_layers=9,
        connect_list=["32", "64", "128", "256"],
    ).to(device)
    checkpoint = torch.load(args.checkpoint.resolve(), map_location="cpu")
    network.load_state_dict(checkpoint["params_ema"])
    network.eval()

    def infer(tensor: torch.Tensor) -> torch.Tensor:
        return network(tensor, w=args.fidelity, adain=True)[0]

    return infer


def benchmark_batch(
    infer,
    *,
    batch_size: int,
    warmup: int,
    iterations: int,
    amp: bool,
    device: torch.device,
) -> tuple[float, float]:
    input_tensor = torch.randn(batch_size, 3, 512, 512, device=device)
    autocast = (
        lambda: torch.autocast(device_type="cuda", dtype=torch.float16)
        if amp
        else contextlib.nullcontext()
    )
    torch.cuda.reset_peak_memory_stats(device)
    with torch.inference_mode():
        for _ in range(warmup):
            with autocast():
                infer(input_tensor)
        torch.cuda.synchronize(device)
        start = torch.cuda.Event(enable_timing=True)
        end = torch.cuda.Event(enable_timing=True)
        start.record()
        for _ in range(iterations):
            with autocast():
                infer(input_tensor)
        end.record()
        torch.cuda.synchronize(device)
    batch_ms = start.elapsed_time(end) / iterations
    peak_mib = torch.cuda.max_memory_allocated(device) / (1024**2)
    del input_tensor
    torch.cuda.empty_cache()
    return batch_ms, peak_mib


def main() -> None:
    args = parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    if args.warmup < 0 or args.iterations <= 0:
        raise ValueError("warmup must be non-negative and iterations must be positive")
    if not args.repo.is_dir():
        raise FileNotFoundError(args.repo)
    if not args.checkpoint.is_file():
        raise FileNotFoundError(args.checkpoint)

    device = torch.device("cuda:0")
    loader = load_gfpgan if args.model == "gfpgan" else load_codeformer
    infer = loader(args, device)
    precision = "AMP FP16" if args.amp else "FP32"
    print(
        f"model={args.model} precision={precision} gpu={torch.cuda.get_device_name(0)} "
        f"warmup={args.warmup} iterations={args.iterations}",
        flush=True,
    )
    print("batch  batch_ms  frame_ms  faces_per_second  peak_mib", flush=True)
    for batch_size in args.batches:
        if batch_size <= 0:
            raise ValueError("batch sizes must be positive")
        try:
            batch_ms, peak_mib = benchmark_batch(
                infer,
                batch_size=batch_size,
                warmup=args.warmup,
                iterations=args.iterations,
                amp=args.amp,
                device=device,
            )
        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache()
            print(f"{batch_size:>5}  OOM", flush=True)
            continue
        frame_ms = batch_ms / batch_size
        throughput = 1000.0 / frame_ms
        print(
            f"{batch_size:>5}  {batch_ms:>8.2f}  {frame_ms:>8.2f}  "
            f"{throughput:>16.2f}  {peak_mib:>8.0f}",
            flush=True,
        )


if __name__ == "__main__":
    main()
