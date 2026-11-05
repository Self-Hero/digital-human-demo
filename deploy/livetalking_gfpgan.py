"""Optional batched GFPGAN restoration for MuseTalk's generated face crops."""

from __future__ import annotations

import contextlib
import math
import os
import queue
import sys
import threading
import time
from collections import deque
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


def _percentile(values: deque[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = max(0, math.ceil(len(ordered) * percentile) - 1)
    return ordered[index]


def _keyframe_indices(frame_count: int, interval: int) -> tuple[int, ...]:
    if frame_count <= 0:
        return ()
    if interval <= 1:
        return tuple(range(frame_count))
    keyframe_count = max(1, math.ceil(frame_count / interval))
    if keyframe_count == 1:
        return (0,)
    last = frame_count - 1
    return tuple(
        round(position * last / (keyframe_count - 1))
        for position in range(keyframe_count)
    )


class _DeferredFrame:
    def __init__(self, original: np.ndarray) -> None:
        self.original = original
        self.result = original
        self.ready = threading.Event()


class _SharedGFPGANRuntime:
    """Process-wide network and CUDA stream; request queues stay per session."""

    def __init__(
        self,
        repo: Path,
        checkpoint: Path,
        batch_size: int,
        amp: bool,
        async_enabled: bool,
    ) -> None:
        self.repo = repo
        self.checkpoint = checkpoint
        self.batch_size = batch_size
        self.amp = amp
        self.device = torch.device("cuda:0")
        self.stream = None
        self.network = None
        self._inference_lock = threading.Lock()
        if async_enabled and torch.cuda.is_available():
            self.stream = torch.cuda.Stream(device=self.device)
        self._load_and_warm_up()

    def _autocast(self):
        if self.amp:
            return torch.autocast(device_type="cuda", dtype=torch.float16)
        return contextlib.nullcontext()

    def _stream_context(self):
        if self.stream is not None:
            return torch.cuda.stream(self.stream)
        return contextlib.nullcontext()

    def _load_and_warm_up(self) -> None:
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

        # Match the live tensor layout and internal inference batch.
        warmup = torch.zeros(
            self.batch_size, 256, 256, 3, device=self.device
        ).permute(0, 3, 1, 2)
        warmup = F.interpolate(
            warmup, size=(512, 512), mode="bicubic", align_corners=False
        )
        with self._stream_context(), torch.inference_mode(), self._autocast():
            self.network(warmup, return_rgb=False, weight=0.5)
        if self.stream is not None:
            self.stream.synchronize()
        else:
            torch.cuda.synchronize(self.device)
        logger.info(
            "Realtime GFPGAN runtime preloaded: model=%s batch=%d amp=%s",
            self.checkpoint,
            self.batch_size,
            self.amp,
        )

    def restore(self, frames: np.ndarray) -> np.ndarray:
        if self.network is None:
            raise RuntimeError("GFPGAN network is not loaded")
        if not isinstance(frames, np.ndarray) or frames.ndim != 4:
            raise ValueError("GFPGAN expects an NHWC frame batch")

        with self._inference_lock, self._stream_context(), torch.inference_mode():
            height, width = frames.shape[1:3]
            rgb = np.ascontiguousarray(frames[..., ::-1])
            tensor = torch.from_numpy(rgb).permute(0, 3, 1, 2)
            tensor = tensor.to(self.device, dtype=torch.float32).div_(127.5).sub_(1.0)
            tensor = F.interpolate(
                tensor, size=(512, 512), mode="bicubic", align_corners=False
            )

            restored_batches = []
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
                restored, size=(height, width), mode="bicubic", align_corners=False
            )
            restored = restored.clamp_(-1.0, 1.0).add_(1.0).mul_(127.5)
            restored = restored.round_().byte().permute(0, 2, 3, 1).cpu().numpy()
        return np.ascontiguousarray(restored[..., ::-1])


_RUNTIME_LOCK = threading.Lock()
_RUNTIMES: dict[tuple[str, str, int, bool, bool], _SharedGFPGANRuntime] = {}
_RUNTIME_FAILURES: set[tuple[str, str, int, bool, bool]] = set()


def _runtime_settings() -> tuple[Path, Path, int, bool, bool]:
    repo = Path(os.getenv("LIVETALKING_GFPGAN_REPO", "/data/GFPGAN"))
    checkpoint = Path(
        os.getenv(
            "LIVETALKING_GFPGAN_MODEL",
            "/data/GFPGAN/experiments/pretrained_models/GFPGANv1.4.pth",
        )
    )
    batch_size = _integer("LIVETALKING_GFPGAN_BATCH_SIZE", 2, 1, 8)
    amp = _enabled("LIVETALKING_GFPGAN_AMP", "1")
    async_enabled = _enabled("LIVETALKING_GFPGAN_ASYNC", "1")
    return repo, checkpoint, batch_size, amp, async_enabled


def _get_shared_runtime() -> _SharedGFPGANRuntime:
    repo, checkpoint, batch_size, amp, async_enabled = _runtime_settings()
    key = (
        str(repo.resolve()),
        str(checkpoint.resolve()),
        batch_size,
        amp,
        async_enabled,
    )
    with _RUNTIME_LOCK:
        if key in _RUNTIME_FAILURES:
            raise RuntimeError("GFPGAN process runtime failed during preload")
        runtime = _RUNTIMES.get(key)
        if runtime is not None:
            return runtime
        try:
            runtime = _SharedGFPGANRuntime(
                repo, checkpoint, batch_size, amp, async_enabled
            )
        except Exception:
            _RUNTIME_FAILURES.add(key)
            raise
        _RUNTIMES[key] = runtime
        return runtime


def preload_realtime_gfpgan() -> _SharedGFPGANRuntime | None:
    """Load and warm the shared model during service startup when enabled."""
    if not _enabled("LIVETALKING_GFPGAN", "0"):
        return None
    try:
        return _get_shared_runtime()
    except Exception:
        logger.exception("Disabling realtime GFPGAN because preload failed")
        return None


class RealtimeGFPGANEnhancer:
    """Per-session async queue backed by a process-wide GFPGAN network."""

    def __init__(self) -> None:
        self.enabled = _enabled("LIVETALKING_GFPGAN", "0")
        self.blend = _floating("LIVETALKING_GFPGAN_BLEND", 0.6, 0.0, 1.0)
        self.interval = _integer("LIVETALKING_GFPGAN_INTERVAL", 1, 1, 4)
        self.async_enabled = _enabled("LIVETALKING_GFPGAN_ASYNC", "1")
        self.wait_seconds = _integer(
            "LIVETALKING_GFPGAN_WAIT_MS", 250, 20, 2000
        ) / 1000.0
        self.runtime = None
        self._batch_count = 0
        self._timeout_count = 0
        self._bypass_count = 0
        self._latencies_ms: deque[float] = deque(maxlen=100)
        self._jobs: queue.Queue = queue.Queue(maxsize=2)
        self._worker = None

        if self.enabled:
            self.runtime = preload_realtime_gfpgan()
            self.enabled = self.runtime is not None
        if self.enabled and self.async_enabled:
            self._worker = threading.Thread(
                target=self._run_worker,
                name="livetalking-gfpgan",
                daemon=True,
            )
            self._worker.start()

        if self.enabled:
            logger.info(
                "Realtime GFPGAN: enabled interval=%d blend=%.2f async=%s wait=%dms",
                self.interval,
                self.blend,
                self.async_enabled,
                round(self.wait_seconds * 1000),
            )
        else:
            logger.info("Realtime GFPGAN: disabled")

    def _interpolate_restoration(
        self,
        frames: np.ndarray,
        keyframe_indices: tuple[int, ...],
        restored_keyframes: np.ndarray,
    ) -> np.ndarray:
        original = frames.astype(np.float32)
        key_original = original[list(keyframe_indices)]
        key_residuals = restored_keyframes.astype(np.float32) - key_original
        residuals = np.empty_like(original)

        if len(keyframe_indices) == 1:
            residuals[:] = key_residuals[0]
        else:
            for segment in range(len(keyframe_indices) - 1):
                left = keyframe_indices[segment]
                right = keyframe_indices[segment + 1]
                span = right - left
                for frame_index in range(left, right + 1):
                    alpha = (frame_index - left) / span
                    residuals[frame_index] = (
                        key_residuals[segment] * (1.0 - alpha)
                        + key_residuals[segment + 1] * alpha
                    )

        return np.clip(original + residuals * self.blend, 0, 255).astype(np.uint8)

    def _enhance_batch(self, frames: np.ndarray) -> np.ndarray:
        if not self.enabled or self.runtime is None or self.blend <= 0:
            return frames
        if not isinstance(frames, np.ndarray) or frames.ndim != 4:
            logger.error("Disabling realtime GFPGAN: unexpected frame batch shape")
            self.enabled = False
            return frames

        started = time.perf_counter()
        try:
            indices = _keyframe_indices(len(frames), self.interval)
            restored_keyframes = self.runtime.restore(frames[list(indices)])
            if len(indices) == len(frames):
                restored = np.clip(
                    restored_keyframes.astype(np.float32) * self.blend
                    + frames.astype(np.float32) * (1.0 - self.blend),
                    0,
                    255,
                ).astype(np.uint8)
            else:
                restored = self._interpolate_restoration(
                    frames, indices, restored_keyframes
                )

            elapsed_ms = (time.perf_counter() - started) * 1000.0
            self._latencies_ms.append(elapsed_ms)
            self._batch_count += 1
            if self._batch_count <= 3 or self._batch_count % 25 == 0:
                logger.info(
                    "Realtime GFPGAN batch: frames=%d restored=%d interval=%d "
                    "elapsed=%.2fms p95=%.2fms timeouts=%d bypassed=%d",
                    len(frames),
                    len(indices),
                    self.interval,
                    elapsed_ms,
                    _percentile(self._latencies_ms, 0.95),
                    self._timeout_count,
                    self._bypass_count,
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
            self._bypass_count += 1
            logger.warning("Realtime GFPGAN queue full; bypassing one batch")
            return frames
        return deferred

    def resolve_frame(self, frame):
        if not isinstance(frame, _DeferredFrame):
            return frame
        if not frame.ready.wait(self.wait_seconds):
            self._timeout_count += 1
            logger.warning("Realtime GFPGAN timed out; using the original face crop")
            return frame.original
        return frame.result

    def _run_worker(self) -> None:
        while True:
            frames, deferred = self._jobs.get()
            try:
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
