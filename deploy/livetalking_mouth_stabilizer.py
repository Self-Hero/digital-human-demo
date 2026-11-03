"""Lightweight temporal stabilization for MuseTalk's generated mouth region."""

from __future__ import annotations

import os
import time

import cv2
import numpy as np

try:
    # LiveTalking configures this logger for both its service journal and log file.
    from utils.logger import logger
except ImportError:  # Allow standalone checks outside a LiveTalking checkout.
    import logging

    logger = logging.getLogger(__name__)


def _env_enabled(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return min(maximum, max(minimum, value))


class MouthTemporalStabilizer:
    """Suppress small lip and tooth flicker without delaying video frames."""

    def __init__(self) -> None:
        self.enabled = _env_enabled("LIVETALKING_MOUTH_STABILIZER", "0")
        self.strength = _env_float(
            "LIVETALKING_MOUTH_STRENGTH", 0.18, 0.0, 0.35
        )
        self.motion_threshold = _env_float(
            "LIVETALKING_MOUTH_MOTION_THRESHOLD", 0.12, 0.02, 0.5
        )
        self.reset_gap_seconds = _env_float(
            "LIVETALKING_MOUTH_RESET_GAP_SECONDS", 0.75, 0.2, 5.0
        )
        self._previous: np.ndarray | None = None
        self._last_frame_at = 0.0
        self._mask_cache: dict[tuple[int, int], np.ndarray] = {}
        logger.info(
            "MuseTalk mouth stabilizer: enabled=%s strength=%.3f threshold=%.3f",
            self.enabled,
            self.strength,
            self.motion_threshold,
        )

    def reset(self) -> None:
        self._previous = None
        self._last_frame_at = 0.0

    def apply(self, frame: np.ndarray, bbox) -> np.ndarray:
        if not self.enabled or self.strength <= 0:
            return frame

        roi_box = self._mouth_box(frame.shape, bbox)
        if roi_box is None:
            self.reset()
            return frame
        x1, y1, x2, y2 = roi_box
        current = frame[y1:y2, x1:x2].copy()
        if current.size == 0:
            self.reset()
            return frame

        now = time.monotonic()
        if now - self._last_frame_at > self.reset_gap_seconds:
            self._previous = None
        self._last_frame_at = now

        if self._previous is None:
            self._previous = current
            return frame

        previous = cv2.resize(
            self._previous,
            (current.shape[1], current.shape[0]),
            interpolation=cv2.INTER_LINEAR,
        )
        aligned_previous = self._align_previous(previous, current)
        current_gray = cv2.cvtColor(current, cv2.COLOR_BGR2GRAY)
        previous_gray = cv2.cvtColor(aligned_previous, cv2.COLOR_BGR2GRAY)
        motion = float(
            np.mean(
                np.abs(
                    current_gray.astype(np.float32)
                    - previous_gray.astype(np.float32)
                )
            )
            / 255.0
        )
        weight = self.strength * max(
            0.0, 1.0 - motion / self.motion_threshold
        )

        if weight > 0.001:
            blended = cv2.addWeighted(
                current,
                1.0 - weight,
                aligned_previous,
                weight,
                0.0,
            )
            mask = self._soft_mask(current.shape[0], current.shape[1])
            result = (
                current.astype(np.float32) * (1.0 - mask)
                + blended.astype(np.float32) * mask
            ).clip(0, 255).astype(np.uint8)
            frame[y1:y2, x1:x2] = result
            self._previous = result
        else:
            self._previous = current
        return frame

    @staticmethod
    def _mouth_box(frame_shape, bbox) -> tuple[int, int, int, int] | None:
        height, width = frame_shape[:2]
        x1, y1, x2, y2 = (int(value) for value in bbox)
        face_width = x2 - x1
        face_height = y2 - y1
        if face_width < 16 or face_height < 16:
            return None

        mouth_x1 = max(0, x1 + int(face_width * 0.23))
        mouth_x2 = min(width, x1 + int(face_width * 0.77))
        mouth_y1 = max(0, y1 + int(face_height * 0.58))
        mouth_y2 = min(height, y1 + int(face_height * 0.94))
        if mouth_x2 - mouth_x1 < 8 or mouth_y2 - mouth_y1 < 8:
            return None
        return mouth_x1, mouth_y1, mouth_x2, mouth_y2

    @staticmethod
    def _align_previous(previous: np.ndarray, current: np.ndarray) -> np.ndarray:
        previous_gray = cv2.cvtColor(previous, cv2.COLOR_BGR2GRAY)
        current_gray = cv2.cvtColor(current, cv2.COLOR_BGR2GRAY)
        # Flow from current to previous provides the source coordinate for each
        # current pixel, which can be consumed directly by cv2.remap().
        flow = cv2.calcOpticalFlowFarneback(
            current_gray,
            previous_gray,
            None,
            0.5,
            2,
            11,
            2,
            5,
            1.1,
            0,
        )
        grid_x, grid_y = np.meshgrid(
            np.arange(current.shape[1], dtype=np.float32),
            np.arange(current.shape[0], dtype=np.float32),
        )
        return cv2.remap(
            previous,
            grid_x + flow[..., 0],
            grid_y + flow[..., 1],
            interpolation=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT101,
        )

    def _soft_mask(self, height: int, width: int) -> np.ndarray:
        key = (height, width)
        cached = self._mask_cache.get(key)
        if cached is not None:
            return cached

        mask = np.zeros((height, width), dtype=np.float32)
        cv2.ellipse(
            mask,
            (width // 2, height // 2),
            (max(1, width // 2 - 1), max(1, height // 2 - 1)),
            0,
            0,
            360,
            1.0,
            -1,
        )
        blur_size = max(3, (min(height, width) // 5) | 1)
        mask = cv2.GaussianBlur(mask, (blur_size, blur_size), 0)
        mask = mask[..., None]
        self._mask_cache[key] = mask
        return mask
