import importlib.util
from pathlib import Path

import cv2
import numpy as np


MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "deploy"
    / "livetalking_mouth_stabilizer.py"
)
SPEC = importlib.util.spec_from_file_location("livetalking_mouth_stabilizer", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
MouthTemporalStabilizer = MODULE.MouthTemporalStabilizer


def test_verified_realtime_profile_defaults(monkeypatch) -> None:
    monkeypatch.delenv("LIVETALKING_MOUTH_MOTION_THRESHOLD", raising=False)
    monkeypatch.delenv("LIVETALKING_MOUTH_TRANSITION_FRAMES", raising=False)

    stabilizer = MouthTemporalStabilizer()

    assert stabilizer.motion_threshold == 0.15
    assert stabilizer.transition_frames == 4
    assert stabilizer.inner_detail_enabled
    assert stabilizer.inner_detail_strength == 0.55


def test_local_compositor_preserves_face_outside_mouth(monkeypatch) -> None:
    monkeypatch.setenv("LIVETALKING_MOUTH_LOCAL_COMPOSITOR", "1")
    monkeypatch.setenv("LIVETALKING_MOUTH_STABILIZER", "0")
    monkeypatch.setenv("LIVETALKING_MOUTH_COLOR_MATCH", "0")
    monkeypatch.setenv("LIVETALKING_MOUTH_SHARPEN", "0")

    reference = np.full((120, 120, 3), 40, dtype=np.uint8)
    generated = np.full((120, 120, 3), 210, dtype=np.uint8)
    result = MouthTemporalStabilizer().apply(
        generated.copy(), (20, 10, 100, 110), reference
    )

    assert np.array_equal(result[15, 25], reference[15, 25])
    assert np.array_equal(result[40, 60], reference[40, 60])
    assert float(result[82, 60].mean()) > float(reference[82, 60].mean()) + 100


def test_local_compositor_mask_size_is_configurable(monkeypatch) -> None:
    monkeypatch.setenv("LIVETALKING_MOUTH_LOCAL_COMPOSITOR", "1")
    monkeypatch.setenv("LIVETALKING_MOUTH_STABILIZER", "0")
    monkeypatch.setenv("LIVETALKING_MOUTH_COLOR_MATCH", "0")
    monkeypatch.setenv("LIVETALKING_MOUTH_SHARPEN", "0")
    monkeypatch.setenv("LIVETALKING_MOUTH_MASK_RADIUS_X", "0.18")
    monkeypatch.setenv("LIVETALKING_MOUTH_MASK_RADIUS_Y", "0.09")
    monkeypatch.setenv("LIVETALKING_MOUTH_MASK_FEATHER", "0.01")

    reference = np.full((120, 120, 3), 40, dtype=np.uint8)
    generated = np.full((120, 120, 3), 210, dtype=np.uint8)
    result = MouthTemporalStabilizer().apply(
        generated.copy(), (20, 10, 100, 110), reference
    )

    assert np.array_equal(result[82, 40], reference[82, 40])
    assert float(result[95, 60].mean()) < float(reference[95, 60].mean()) + 10
    assert float(result[82, 60].mean()) > float(reference[82, 60].mean()) + 100


def test_local_compositor_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setenv("LIVETALKING_MOUTH_LOCAL_COMPOSITOR", "0")
    monkeypatch.setenv("LIVETALKING_MOUTH_STABILIZER", "0")

    reference = np.full((64, 64, 3), 20, dtype=np.uint8)
    generated = np.full((64, 64, 3), 200, dtype=np.uint8)
    result = MouthTemporalStabilizer().apply(
        generated.copy(), (8, 8, 56, 56), reference
    )

    assert np.array_equal(result, generated)


def test_detail_transfer_restores_skin_texture_but_protects_mouth(
    monkeypatch,
) -> None:
    monkeypatch.setenv("LIVETALKING_MOUTH_DETAIL_TRANSFER", "2")

    stabilizer = MouthTemporalStabilizer()
    assert stabilizer.detail_transfer_strength == 2.0
    generated = np.full((100, 100, 3), 128, dtype=np.uint8)
    checker = (np.indices((100, 100)).sum(axis=0) % 2) * 40 - 20
    reference = np.clip(
        generated.astype(np.int16) + checker[..., None], 0, 255
    ).astype(np.uint8)

    result = stabilizer._transfer_reference_detail(generated, reference)

    assert np.array_equal(result[70:75, 48:53], generated[70:75, 48:53])
    assert float(result[68:78, 12:22].std()) > 5.0


def test_adaptive_temporal_mask_protects_inner_mouth(monkeypatch) -> None:
    monkeypatch.setenv("LIVETALKING_MOUTH_ADAPTIVE", "1")
    monkeypatch.setenv("LIVETALKING_MOUTH_INNER_STRENGTH", "0.08")

    stabilizer = MouthTemporalStabilizer()
    mask = stabilizer._adaptive_temporal_mask(80, 100)[..., 0]

    inner_mouth = float(mask[38, 50])
    lip_boundary = float(mask[38, 20])
    assert inner_mouth < 0.2
    assert lip_boundary > 0.65


def test_adaptive_motion_reacts_fast_and_releases_slowly(monkeypatch) -> None:
    monkeypatch.setenv("LIVETALKING_MOUTH_STABILIZER", "1")
    monkeypatch.setenv("LIVETALKING_MOUTH_ADAPTIVE", "1")
    monkeypatch.setenv("LIVETALKING_MOUTH_STRENGTH", "0.30")

    stabilizer = MouthTemporalStabilizer()
    first = np.full((96, 96, 3), 80, dtype=np.uint8)
    moving = first.copy()
    moving[56:72, 38:58] = 180
    bbox = (16, 8, 80, 88)

    stabilizer.apply(first.copy(), bbox)
    stabilizer.apply(moving.copy(), bbox)
    high_motion = stabilizer._motion_ema.copy()
    stabilizer.apply(moving.copy(), bbox)

    assert float(stabilizer._motion_ema.mean()) < float(high_motion.mean())
    assert float(stabilizer._motion_ema.mean()) > 0.0


def test_inner_detail_stabilizer_reduces_texture_flicker_without_shape_blend(
    monkeypatch,
) -> None:
    monkeypatch.setenv("LIVETALKING_MOUTH_INNER_DETAIL_STABILIZER", "1")
    monkeypatch.setenv("LIVETALKING_MOUTH_INNER_DETAIL_STRENGTH", "0.5")
    stabilizer = MouthTemporalStabilizer()
    monkeypatch.setattr(
        stabilizer,
        "_align_previous_detail",
        lambda previous, current: previous,
    )

    height, width = 80, 100
    current = np.full((height, width, 3), 128, dtype=np.uint8)
    previous = current.copy()
    checker = ((np.indices((24, 40)).sum(axis=0) % 2) * 48 - 24).astype(
        np.int16
    )
    current[28:52, 30:70] = np.clip(
        current[28:52, 30:70].astype(np.int16) + checker[..., None],
        0,
        255,
    ).astype(np.uint8)
    previous[28:52, 30:70] = np.clip(
        previous[28:52, 30:70].astype(np.int16) - checker[..., None],
        0,
        255,
    ).astype(np.uint8)

    result = stabilizer._stabilize_inner_detail(current, previous)
    current_high = current.astype(np.float32) - cv2.GaussianBlur(
        current.astype(np.float32), (0, 0), 1.0
    )
    previous_high = previous.astype(np.float32) - cv2.GaussianBlur(
        previous.astype(np.float32), (0, 0), 1.0
    )
    result_high = result.astype(np.float32) - cv2.GaussianBlur(
        result.astype(np.float32), (0, 0), 1.0
    )
    center = np.s_[32:48, 35:65]

    before = float(np.mean(np.abs(current_high[center] - previous_high[center])))
    after = float(np.mean(np.abs(result_high[center] - previous_high[center])))
    current_low = cv2.GaussianBlur(current.astype(np.float32), (0, 0), 3.0)
    result_low = cv2.GaussianBlur(result.astype(np.float32), (0, 0), 3.0)

    assert after < before
    assert float(np.mean(np.abs(result_low - current_low))) < 0.5
    assert np.array_equal(result[:8, :8], current[:8, :8])


def test_inner_detail_stabilizer_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setenv("LIVETALKING_MOUTH_INNER_DETAIL_STABILIZER", "0")
    stabilizer = MouthTemporalStabilizer()
    current = np.full((40, 50, 3), 200, dtype=np.uint8)
    previous = np.full((40, 50, 3), 40, dtype=np.uint8)

    assert np.array_equal(
        stabilizer._stabilize_inner_detail(current, previous), current
    )


def test_batch_seam_blends_only_first_two_batch_frames(monkeypatch) -> None:
    monkeypatch.setenv("LIVETALKING_MOUTH_LOCAL_COMPOSITOR", "0")
    monkeypatch.setenv("LIVETALKING_MOUTH_STABILIZER", "1")
    monkeypatch.setenv("LIVETALKING_MOUTH_STRENGTH", "0")
    monkeypatch.setenv("LIVETALKING_MOUTH_BATCH_SEAM_FRAMES", "2")
    monkeypatch.setenv("LIVETALKING_MOUTH_BATCH_SEAM_STRENGTH", "0.5")

    stabilizer = MouthTemporalStabilizer()
    bbox = (10, 10, 90, 90)
    previous = np.full((100, 100, 3), 40, dtype=np.uint8)
    current = np.full((100, 100, 3), 200, dtype=np.uint8)

    stabilizer.apply(previous.copy(), bbox, batch_position=7)
    first = stabilizer.apply(current.copy(), bbox, batch_position=0)
    second = stabilizer.apply(current.copy(), bbox, batch_position=1)
    third = stabilizer.apply(current.copy(), bbox, batch_position=2)

    center = (69, 49)
    assert 118 <= int(first[center].mean()) <= 122
    assert 178 <= int(second[center].mean()) <= 182
    assert int(third[center].mean()) == 200
