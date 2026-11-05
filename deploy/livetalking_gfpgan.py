"""Optional batched GFPGAN restoration for MuseTalk's generated face crops."""

from __future__ import annotations

import contextlib
import os
import queue
import sys
import threading
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

try:
    from utils.logger import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)


def _enabled(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return min(maximum, max(minimum, value))


def _floating(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return min(maximum, max(minimum, value))


class _DeferredFrame:
    def __init__(self, original: np.ndarray) -> None:
        self.original = original
        self.result = original
        self.ready = threading.Event()


class RealtimeGFPGANEnhancer:
    """Restore decoded MuseTalk batches without detection or filesystem I/O."""

    def __init__(self) -> None:
        self.enabled = _enabled("LIVETALKING_GFPGAN", "0")
        self.amp = _enabled("LIVETALKING_GFPGAN_AMP", "1")
        self.batch_size = _integer("LIVETALKING_GFPGAN_BATCH_SIZE", 2, 1, 8)
        self.blend = _floating("LIVETALKING_GFPGAN_BLEND", 0.6, 0.0, 1.0)
        self.async_enabled = _enabled("LIVETALKING_GFPGAN_ASYNC", "1")
        self.wait_seconds = _integer(
            "LIVETALKING_GFPGAN_WAIT_MS", 250, 20, 2000
        ) / 1000.0
        self.repo = Path(os.getenv("LIVETALKING_GFPGAN_REPO", "/data/GFPGAN"))
        self.checkpoint = Path(
            os.getenv(
                "LIVETALKING_GFPGAN_MODEL",
                "/data/GFPGAN/experiments/pretrained_models/GFPGANv1.4.pth",
            )
        )
        self.device = torch.device("cuda:0")
        self.network = None
        self._batch_count = 0
        self._jobs: queue.Queue = queue.Queue(maxsize=2)
        self._worker = None
        self._stream = None
        if self.enabled:
            try:
                if self.async_enabled and torch.cuda.is_available():
                    self._stream = torch.cuda.Stream(device=self.device)
                self._load()
                if self.async_enabled:
                    self._worker = threading.Thread(
                        target=self._run_worker,
                        name="livetalking-gfpgan",
                        daemon=True,
                    )
                    self._worker.start()
            except Exception:
                self.enabled = False
                logger.exception(
                    "Disabling realtime GFPGAN because initialization failed"
                )
        else:
            logger.info("Realtime GFPGAN: disabled")

    def _load(self) -> None:
        if not torch.cuda.is_available():
            raise RuntimeError("GFPGAN requires CUDA")
        if not self.repo.is_dir():
            raise FileNotFoundError(f"GFPGAN repository not found: {self.repo}")
        if not self.checkpoint.is_file():
            raise FileNotFoundError(f"GFPGAN checkpoint not found: {self.checkpoint}")

        repo = str(self.repo.resolve())
        if repo not in sys.path:
            sys.path.insert(0, repo)
        from gfpgan.archs.gfpganv1_clean_arch import GFPGANv1Clean

        network = GFPGANv1Clean(
            out_size=512,
            num_style_feat=512,
            channel_multiplier=2,
            decoder_load_path=None,
            fix_decoder=False,
            num_mlp=8,
            input_is_latent=True,
            different_w=True,
            narrow=1,
            sft_half=True,
        ).to(self.device)
        try:
            checkpoint = torch.load(
                self.checkpoint.resolve(), map_location="cpu", weights_only=True
            )
        except TypeError:
            checkpoint = torch.load(self.checkpoint.resolve(), map_location="cpu")
        state_dict = checkpoint.get("params_ema", checkpoint.get("params", checkpoint))
        network.load_state_dict(state_dict, strict=True)
        network.eval()
        self.network = network

        # Match the non-contiguous HWC-to-CHW layout used by real decoded frames.
        warmup = torch.zeros(
            self.batch_size, 256, 256, 3, device=self.device
        ).permute(0, 3, 1, 2)
        warmup = F.interpolate(
            warmup,
            size=(512, 512),
            mode="bicubic",
            align_corners=False,
        )
        stream_context = (
            torch.cuda.stream(self._stream)
            if self._stream is not None
            else contextlib.nullcontext()
        )
        with stream_context, torch.inference_mode(), self._autocast():
            self.network(warmup, return_rgb=False, weight=0.5)
        if self._stream is not None:
            self._stream.synchronize()
        else:
            torch.cuda.synchronize(self.device)
        logger.info(
            "Realtime GFPGAN: enabled model=%s batch=%d amp=%s blend=%.2f async=%s",
            self.checkpoint,
            self.batch_size,
            self.amp,
            self.blend,
            self.async_enabled,
        )

    def _autocast(self):
        if self.amp:
            return torch.autocast(device_type="cuda", dtype=torch.float16)
        return contextlib.nullcontext()

    def _enhance_batch(self, frames: np.ndarray) -> np.ndarray:
        if not self.enabled or self.network is None or self.blend <= 0:
            return frames
        if not isinstance(frames, np.ndarray) or frames.ndim != 4:
            logger.error("Disabling realtime GFPGAN: unexpected frame batch shape")
            self.enabled = False
            return frames

        started = time.perf_counter()
        try:
            original = frames
            height, width = frames.shape[1:3]
            rgb = np.ascontiguousarray(frames[..., ::-1])
            tensor = torch.from_numpy(rgb).permute(0, 3, 1, 2)
            tensor = tensor.to(self.device, dtype=torch.float32).div_(127.5).sub_(1.0)
            tensor = F.interpolate(
                tensor,
                size=(512, 512),
                mode="bicubic",
                align_corners=False,
            )

            restored_batches = []
            with torch.inference_mode():
                for start in range(0, tensor.shape[0], self.batch_size):
                    with self._autocast():
                        output = self.network(
                            tensor[start : start + self.batch_size],
                            return_rgb=False,
                            weight=0.5,
                        )[0]
                    restored_batches.append(output.float())
            restored = torch.cat(restored_batches, dim=0)
            restored = F.interpolate(
                restored,
                size=(height, width),
                mode="bicubic",
                align_corners=False,
            )
            restored = restored.clamp_(-1.0, 1.0).add_(1.0).mul_(127.5)
            restored = restored.round_().byte().permute(0, 2, 3, 1).cpu().numpy()
            restored = np.ascontiguousarray(restored[..., ::-1])
            if self.blend < 1.0:
                restored = np.clip(
                    restored.astype(np.float32) * self.blend
                    + original.astype(np.float32) * (1.0 - self.blend),
                    0,
                    255,
                ).astype(np.uint8)

            self._batch_count += 1
            if self._batch_count <= 3 or self._batch_count % 100 == 0:
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                logger.info(
                    "Realtime GFPGAN batch: frames=%d elapsed=%.2fms per_frame=%.2fms",
                    len(frames),
                    elapsed_ms,
                    elapsed_ms / len(frames),
                )
            return restored
        except Exception:
            self.enabled = False
            logger.exception("Disabling realtime GFPGAN after inference failure")
            return frames

    def enhance_batch(self, frames: np.ndarray) -> np.ndarray:
        """Synchronous entry point retained for benchmarks and fallback mode."""
        return self._enhance_batch(frames)

    def enhance_batch_async(self, frames: np.ndarray):
        """Queue restoration while allowing MuseTalk to start its next batch."""
        if not self.enabled or not self.async_enabled or self._worker is None:
            return self._enhance_batch(frames)

        deferred = [_DeferredFrame(frame) for frame in frames]
        try:
            self._jobs.put_nowait((frames, deferred))
        except queue.Full:
            logger.warning("Realtime GFPGAN queue full; bypassing one batch")
            return frames
        return deferred

    def resolve_frame(self, frame):
        if not isinstance(frame, _DeferredFrame):
            return frame
        if not frame.ready.wait(self.wait_seconds):
            logger.warning("Realtime GFPGAN timed out; using the original face crop")
            return frame.original
        return frame.result

    def _run_worker(self) -> None:
        while True:
            frames, deferred = self._jobs.get()
            try:
                if self._stream is None:
                    restored = self._enhance_batch(frames)
                else:
                    with torch.cuda.stream(self._stream):
                        restored = self._enhance_batch(frames)
                for item, result in zip(deferred, restored):
                    item.result = result
            except Exception:
                logger.exception("Realtime GFPGAN worker failed; bypassing batch")
                self.enabled = False
            finally:
                for item in deferred:
                    item.ready.set()
                self._jobs.task_done()
