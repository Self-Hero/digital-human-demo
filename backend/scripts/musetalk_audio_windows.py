"""Plan overlapping Whisper windows for long MuseTalk audio."""

from __future__ import annotations

import math
from typing import NamedTuple


class WhisperWindow(NamedTuple):
    start: int
    stop: int
    valid_features: int
    discard_features: int


def plan_whisper_windows(
    sample_count: int,
    sample_rate: int,
    *,
    window_seconds: int = 30,
    overlap_seconds: int = 2,
    features_per_second: int = 50,
) -> list[WhisperWindow]:
    if sample_count <= 0 or sample_rate <= 0:
        raise ValueError("sample_count and sample_rate must be positive")
    if not 0 <= overlap_seconds < window_seconds:
        raise ValueError("overlap_seconds must be smaller than window_seconds")

    window_samples = window_seconds * sample_rate
    overlap_samples = overlap_seconds * sample_rate
    overlap_features = overlap_seconds * features_per_second
    windows = []
    start = 0
    while start < sample_count:
        stop = min(sample_count, start + window_samples)
        valid_features = math.ceil(
            (stop - start) / sample_rate * features_per_second
        )
        windows.append(
            WhisperWindow(
                start=start,
                stop=stop,
                valid_features=valid_features,
                discard_features=overlap_features if start else 0,
            )
        )
        if stop == sample_count:
            break
        start = stop - overlap_samples
    return windows
