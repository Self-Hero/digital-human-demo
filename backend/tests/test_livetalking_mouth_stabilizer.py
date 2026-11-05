import importlib.util
from pathlib import Path

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
