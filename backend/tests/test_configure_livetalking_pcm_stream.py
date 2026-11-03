from pathlib import Path

from scripts.configure_livetalking_pcm_stream import (
    IMPORT_ANCHOR,
    PATCHED_IMPORT,
    PATCHED_ROUTE,
    ROUTE_ANCHOR,
    configure,
)


def test_configure_registers_pcm_websocket_and_is_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "routes.py"
    original = IMPORT_ANCHOR + "\n\ndef setup_routes(app):\n" + ROUTE_ANCHOR
    source.write_text(original, encoding="utf-8")

    first_result = configure(source)
    first_text = source.read_text(encoding="utf-8")
    second_result = configure(source)

    assert first_result.startswith("configured; backup:")
    assert second_result == "already configured"
    assert PATCHED_IMPORT in first_text
    assert PATCHED_ROUTE in first_text
    assert source.read_text(encoding="utf-8") == first_text
    assert source.with_suffix(".py.before-pcm-stream").read_text(
        encoding="utf-8"
    ) == original


def test_configure_rejects_unknown_routes_source(tmp_path: Path) -> None:
    source = tmp_path / "routes.py"
    source.write_text("def setup_routes(app):\n    pass\n", encoding="utf-8")

    try:
        configure(source)
    except RuntimeError as exc:
        assert "expected route anchors" in str(exc)
    else:
        raise AssertionError("configure() should reject an unknown source layout")
