"""The legacy exceptions to the layer contract are frozen (reviewer 2026-11-03): the list may only shrink."""

from pathlib import Path

FROZEN_LEGACY_IGNORES = 13  # lower this number when a module moves behind a port; never raise it


def test_legacy_layer_exceptions_do_not_grow():
    text = (Path(__file__).parents[2] / ".importlinter").read_text(encoding="utf-8")
    ignores = [ln for ln in text.splitlines() if "->" in ln and not ln.strip().startswith("#")]
    assert len(ignores) <= FROZEN_LEGACY_IGNORES, (
        f"{len(ignores)} ignore_imports in .importlinter (frozen at {FROZEN_LEGACY_IGNORES}): put new code "
        "behind a port in application/ports.py instead of adding an exception"
    )
