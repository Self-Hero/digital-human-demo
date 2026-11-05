from scripts.musetalk_audio_windows import plan_whisper_windows


def test_short_audio_uses_one_whisper_window() -> None:
    windows = plan_whisper_windows(1000, 100)

    assert windows == [(0, 1000, 500, 0)]


def test_long_audio_is_windowed_without_losing_duration() -> None:
    windows = plan_whisper_windows(3588, 100)

    assert windows == [
        (0, 3000, 1500, 0),
        (2800, 3588, 394, 100),
    ]
    assert sum(window.valid_features - window.discard_features for window in windows) == 1794
