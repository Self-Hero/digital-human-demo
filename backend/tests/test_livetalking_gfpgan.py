import importlib.util
import sys
import types
from pathlib import Path

import pytest


np = pytest.importorskip("numpy")


def _load_module(monkeypatch):
    fake_torch = types.ModuleType("torch")
    fake_torch.__path__ = []
    fake_nn = types.ModuleType("torch.nn")
    fake_nn.__path__ = []
    fake_functional = types.ModuleType("torch.nn.functional")
    fake_torch.nn = fake_nn
    fake_nn.functional = fake_functional
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "torch.nn", fake_nn)
    monkeypatch.setitem(sys.modules, "torch.nn.functional", fake_functional)

    path = (
        Path(__file__).resolve().parents[2] / "deploy" / "livetalking_gfpgan.py"
    )
    spec = importlib.util.spec_from_file_location("livetalking_gfpgan_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_interval_two_distributes_four_keyframes_across_batch(monkeypatch) -> None:
    module = _load_module(monkeypatch)

    assert module._keyframe_indices(8, 2) == (0, 2, 5, 7)
    assert module._keyframe_indices(8, 1) == tuple(range(8))


def test_interpolation_preserves_current_frame_and_blends_residual(monkeypatch) -> None:
    module = _load_module(monkeypatch)
    enhancer = module.RealtimeGFPGANEnhancer.__new__(
        module.RealtimeGFPGANEnhancer
    )
    enhancer.blend = 0.5
    enhancer.protect_mouth = False
    enhancer._mouth_gain_cache = {}

    frames = np.arange(8, dtype=np.uint8).reshape(8, 1, 1, 1) * 10
    indices = (0, 2, 5, 7)
    keyframes = frames[list(indices)].astype(np.int16) + np.array(
        [10, 20, 30, 40], dtype=np.int16
    ).reshape(4, 1, 1, 1)

    result = enhancer._interpolate_restoration(
        frames, indices, keyframes.astype(np.uint8)
    )

    # Frame 1 keeps its own value (10) and receives half of the interpolated
    # residual (15), rather than copying frame 0's restored pixels.
    assert int(result[1, 0, 0, 0]) == 17
    assert int(result[3, 0, 0, 0]) == 41
    assert int(result[7, 0, 0, 0]) == 90


def test_mouth_protection_suppresses_only_central_mouth_residual(monkeypatch) -> None:
    module = _load_module(monkeypatch)
    enhancer = module.RealtimeGFPGANEnhancer.__new__(
        module.RealtimeGFPGANEnhancer
    )
    enhancer.protect_mouth = True
    enhancer.mouth_center_y = 0.70
    enhancer.mouth_radius_x = 0.28
    enhancer.mouth_radius_y = 0.15
    enhancer.mouth_feather = 0.30
    enhancer.mouth_residual_scale = 0.0
    enhancer._mouth_gain_cache = {}

    gain = enhancer._mouth_residual_gain(101, 101)

    assert float(gain[70, 50, 0]) == 0.0
    assert float(gain[10, 50, 0]) == 1.0
    assert 0.0 < float(gain[70, 75, 0]) < 1.0
