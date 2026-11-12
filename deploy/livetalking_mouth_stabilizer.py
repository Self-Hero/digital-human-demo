"""Local mouth compositing and temporal stabilization for MuseTalk."""

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
        self.local_compositor = _env_enabled(
            "LIVETALKING_MOUTH_LOCAL_COMPOSITOR", "1"
        )
        self.color_match_strength = _env_float(
            "LIVETALKING_MOUTH_COLOR_MATCH", 0.35, 0.0, 1.0
        )
        self.sharpen_strength = _env_float(
            "LIVETALKING_MOUTH_SHARPEN", 0.18, 0.0, 0.6
        )
        self.local_mask_center_y = _env_float(
            "LIVETALKING_MOUTH_MASK_CENTER_Y", 0.72, 0.55, 0.90
        )
        self.local_mask_radius_x = _env_float(
            "LIVETALKING_MOUTH_MASK_RADIUS_X", 0.38, 0.15, 0.45
        )
        self.local_mask_radius_y = _env_float(
            "LIVETALKING_MOUTH_MASK_RADIUS_Y", 0.27, 0.08, 0.30
        )
        self.local_mask_feather = _env_float(
            "LIVETALKING_MOUTH_MASK_FEATHER", 0.035, 0.01, 0.08
        )
        self.optical_flow = _env_enabled(
            "LIVETALKING_MOUTH_OPTICAL_FLOW", "0"
        )
        self.adaptive = _env_enabled(
            "LIVETALKING_MOUTH_ADAPTIVE", "1"
        )
        self.inner_mouth_strength = _env_float(
            "LIVETALKING_MOUTH_INNER_STRENGTH", 0.08, 0.0, 0.4
        )
        self.strength = _env_float(
            "LIVETALKING_MOUTH_STRENGTH", 0.22, 0.0, 0.35
        )
        self.motion_threshold = _env_float(
            "LIVETALKING_MOUTH_MOTION_THRESHOLD", 0.15, 0.02, 0.5
        )
        self.reset_gap_seconds = _env_float(
            "LIVETALKING_MOUTH_RESET_GAP_SECONDS", 0.75, 0.2, 5.0
        )
        self.transition_frames = int(
            _env_float("LIVETALKING_MOUTH_TRANSITION_FRAMES", 4, 0, 12)
        )
        self._previous: np.ndarray | None = None
        self._last_frame_at = 0.0
        self._transition_index = 0
        self._motion_ema: np.ndarray | None = None
        self._mask_cache: dict[tuple[int, int], np.ndarray] = {}
        self._adaptive_mask_cache: dict[tuple[int, int], np.ndarray] = {}
        self._face_mask_cache: dict[tuple[int, int], np.ndarray] = {}
        logger.info(
            "MuseTalk mouth compositor: local=%s color_match=%.3f "
            "sharpen=%.3f mask=(cy=%.3f rx=%.3f ry=%.3f feather=%.3f) "
            "temporal=%s adaptive=%s inner_strength=%.3f optical_flow=%s "
            "strength=%.3f threshold=%.3f transition_frames=%d",
            self.local_compositor,
            self.color_match_strength,
            self.sharpen_strength,
            self.local_mask_center_y,
            self.local_mask_radius_x,
            self.local_mask_radius_y,
            self.local_mask_feather,
            self.enabled,
            self.adaptive,
            self.inner_mouth_strength,
            self.optical_flow,
            self.strength,
            self.motion_threshold,
            self.transition_frames,
        )

    def reset(self) -> None:
        self._previous = None
        self._last_frame_at = 0.0
        self._transition_index = 0
        self._motion_ema = None

    def apply(
        self,
        frame: np.ndarray,
        bbox,
        reference_frame: np.ndarray | None = None,
    ) -> np.ndarray:
        if self.local_compositor and reference_frame is not None:
            frame = self._composite_local_mouth(frame, reference_frame, bbox)

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
            self._transition_index = 0
            self._motion_ema = None
        self._last_frame_at = now

        if self._previous is None:
            current = self._blend_entry(current, reference_frame, roi_box)
            frame[y1:y2, x1:x2] = current
            self._previous = current
            return frame

        previous = cv2.resize(
            self._previous,
            (current.shape[1], current.shape[0]),
            interpolation=cv2.INTER_LINEAR,
        )
        aligned_previous = (
            self._align_previous(previous, current)
            if self.optical_flow
            else previous
        )
        current_gray = cv2.cvtColor(current, cv2.COLOR_BGR2GRAY)
        previous_gray = cv2.cvtColor(aligned_previous, cv2.COLOR_BGR2GRAY)
        motion_map = (
            np.abs(
                current_gray.astype(np.float32)
                - previous_gray.astype(np.float32)
            )
            / 255.0
        )
        if self.adaptive:
            motion_map = cv2.GaussianBlur(motion_map, (0, 0), 1.0)
            if (
                self._motion_ema is None
                or self._motion_ema.shape != motion_map.shape
            ):
                self._motion_ema = motion_map
            else:
                # React quickly to new lip motion, then release slowly so the
                # stabilizer does not flicker on and off near the threshold.
                rising = motion_map >= self._motion_ema
                self._motion_ema = np.where(
                    rising,
                    self._motion_ema * 0.20 + motion_map * 0.80,
                    self._motion_ema * 0.78 + motion_map * 0.22,
                )
            motion_gain = np.clip(
                1.0 - self._motion_ema / self.motion_threshold,
                0.0,
                1.0,
            )
            weight_map = (
                self.strength
                * motion_gain
                * self._adaptive_temporal_mask(
                    current.shape[0], current.shape[1]
                )[..., 0]
            )
            result = (
                current.astype(np.float32) * (1.0 - weight_map[..., None])
                + aligned_previous.astype(np.float32) * weight_map[..., None]
            ).clip(0, 255).astype(np.uint8)
        else:
            motion = float(np.mean(motion_map))
            weight = self.strength * max(
                0.0, 1.0 - motion / self.motion_threshold
            )
            if weight <= 0.001:
                result = current
            else:
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

        result = self._blend_entry(result, reference_frame, roi_box)
        frame[y1:y2, x1:x2] = result
        self._previous = result
        return frame

    def _composite_local_mouth(
        self,
        generated_frame: np.ndarray,
        reference_frame: np.ndarray,
        bbox,
    ) -> np.ndarray:
        """Keep the source face intact outside a feathered lower-mouth mask."""
        face_box = self._clip_face_box(generated_frame.shape, bbox)
        if face_box is None or reference_frame.shape != generated_frame.shape:
            return generated_frame

        x1, y1, x2, y2 = face_box
        generated = generated_frame[y1:y2, x1:x2]
        reference = reference_frame[y1:y2, x1:x2]
        if generated.size == 0:
            return generated_frame

        mask = self._local_face_mask(generated.shape[0], generated.shape[1])
        processed = self._match_boundary_color(generated, reference, mask)
        if self.sharpen_strength > 0:
            blurred = cv2.GaussianBlur(processed, (0, 0), 0.8)
            processed = cv2.addWeighted(
                processed,
                1.0 + self.sharpen_strength,
                blurred,
                -self.sharpen_strength,
                0.0,
            )

        mask_2d = mask[..., 0]
        generated_frame[y1:y2, x1:x2] = cv2.blendLinear(
            processed,
            reference,
            mask_2d,
            1.0 - mask_2d,
        )
        return generated_frame

    def _match_boundary_color(
        self,
        generated: np.ndarray,
        reference: np.ndarray,
        mask: np.ndarray,
    ) -> np.ndarray:
        if self.color_match_strength <= 0:
            return generated

        height, width = mask.shape[:2]
        yy, xx = np.ogrid[:height, :width]
        # Sample skin around the lips and exclude the central mouth itself.
        central_mouth = (
            (xx >= width * 0.30)
            & (xx <= width * 0.70)
            & (yy >= height * 0.58)
            & (yy <= height * 0.86)
        )
        # A sparse skin sample is sufficient for a bounded color offset and
        # avoids scanning the full face ROI on every video frame.
        sample = ((mask[..., 0] > 0.18) & ~central_mouth)[::4, ::4]
        if int(np.count_nonzero(sample)) < 32:
            return generated

        sampled_reference = reference[::4, ::4][sample].astype(np.int16)
        sampled_generated = generated[::4, ::4][sample].astype(np.int16)
        offset = np.median(sampled_reference - sampled_generated, axis=0)
        offset = np.clip(offset, -12.0, 12.0) * self.color_match_strength
        if float(np.max(np.abs(offset))) < 0.5:
            return generated
        return np.clip(
            generated.astype(np.float32) + offset.reshape(1, 1, 3),
            0,
            255,
        ).astype(np.uint8)

    def _blend_entry(
        self,
        generated: np.ndarray,
        reference_frame: np.ndarray | None,
        roi_box: tuple[int, int, int, int],
    ) -> np.ndarray:
        if (
            reference_frame is None
            or self.transition_frames <= 0
            or self._transition_index >= self.transition_frames
        ):
            return generated

        x1, y1, x2, y2 = roi_box
        reference = reference_frame[y1:y2, x1:x2]
        if reference.shape != generated.shape:
            self._transition_index = self.transition_frames
            return generated

        if self.transition_frames == 1:
            generated_weight = 1.0
        else:
            generated_weight = 0.5 + 0.5 * (
                self._transition_index / (self.transition_frames - 1)
            )
        self._transition_index += 1
        if generated_weight >= 1.0:
            return generated

        blended = cv2.addWeighted(
            reference,
            1.0 - generated_weight,
            generated,
            generated_weight,
            0.0,
        )
        mask = (
            self._adaptive_temporal_mask(generated.shape[0], generated.shape[1])
            if self.adaptive
            else self._soft_mask(generated.shape[0], generated.shape[1])
        )
        return (
            generated.astype(np.float32) * (1.0 - mask)
            + blended.astype(np.float32) * mask
        ).clip(0, 255).astype(np.uint8)

    @staticmethod
    def _mouth_box(frame_shape, bbox) -> tuple[int, int, int, int] | None:
        height, width = frame_shape[:2]
        x1, y1, x2, y2 = (int(value) for value in bbox)
        face_width = x2 - x1
        face_height = y2 - y1
        if face_width < 16 or face_height < 16:
            return None

        mouth_x1 = max(0, x1 + int(face_width * 0.18))
        mouth_x2 = min(width, x1 + int(face_width * 0.82))
        mouth_y1 = max(0, y1 + int(face_height * 0.50))
        mouth_y2 = min(height, y1 + int(face_height * 0.98))
        if mouth_x2 - mouth_x1 < 8 or mouth_y2 - mouth_y1 < 8:
            return None
        return mouth_x1, mouth_y1, mouth_x2, mouth_y2

    @staticmethod
    def _clip_face_box(frame_shape, bbox) -> tuple[int, int, int, int] | None:
        height, width = frame_shape[:2]
        x1, y1, x2, y2 = (int(value) for value in bbox)
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(width, x2), min(height, y2)
        if x2 - x1 < 16 or y2 - y1 < 16:
            return None
        return x1, y1, x2, y2

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

    def _adaptive_temporal_mask(self, height: int, width: int) -> np.ndarray:
        key = (height, width)
        cached = self._adaptive_mask_cache.get(key)
        if cached is not None:
            return cached

        outer = self._soft_mask(height, width)[..., 0]
        inner = np.zeros((height, width), dtype=np.float32)
        cv2.ellipse(
            inner,
            (width // 2, int(height * 0.48)),
            (max(1, int(width * 0.24)), max(1, int(height * 0.18))),
            0,
            0,
            360,
            1.0,
            -1,
        )
        sigma = max(1.0, min(height, width) * 0.055)
        inner = cv2.GaussianBlur(inner, (0, 0), sigma)
        mask = outer * (
            1.0 - inner * (1.0 - self.inner_mouth_strength)
        )
        cached = np.clip(mask, 0.0, 1.0)[..., None]
        self._adaptive_mask_cache[key] = cached
        return cached

    def _local_face_mask(self, height: int, width: int) -> np.ndarray:
        key = (height, width)
        cached = self._face_mask_cache.get(key)
        if cached is not None:
            return cached

        mask = np.zeros((height, width), dtype=np.float32)
        cv2.ellipse(
            mask,
            (width // 2, int(height * self.local_mask_center_y)),
            (
                max(1, int(width * self.local_mask_radius_x)),
                max(1, int(height * self.local_mask_radius_y)),
            ),
            0,
            0,
            360,
            1.0,
            -1,
        )
        sigma = max(1.0, min(height, width) * self.local_mask_feather)
        mask = cv2.GaussianBlur(mask, (0, 0), sigma)[..., None]
        self._face_mask_cache[key] = mask
        return mask
