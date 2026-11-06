"""Spec 011 T087: the live reader adapter over parser spec versions, without a database (the YAML v1 fallback)."""

from __future__ import annotations

from pathlib import Path

from automind.acquisition.parsing import registry
from automind.acquisition.parsing.registry import ParserRegistry
from automind.acquisition.pipeline import stamp
from automind.shared.contracts.web import Page

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "html"
KM77 = (FIX / "km77_bmw_520d_g30.html").read_text(encoding="utf-8")
AUTO_DATA = (FIX / "auto_data_bmw_g30_520d.html").read_text(encoding="utf-8")


def _page(url: str, html: str | None, snapshot_id: str | None = None) -> Page:
    return Page(url=url, title="t", text="", html=html, snapshot_id=snapshot_id)


def test_reading_is_named_by_the_version_and_stamped_with_it():
    reg = ParserRegistry.from_yaml()
    got = reg.read(_page("https://www.km77.com/coches/x/datos", KM77), {})
    assert got is not None and got.reader == "km77@v1" and not got.ambiguous
    assert stamp.reader(got, None)["producer_version"] == "km77@v1"


def test_deny_listed_reader_never_runs():
    reg = ParserRegistry.from_yaml()
    assert reg.version_for("https://www.auto-data.net/en/bmw") is None
    assert reg.read(_page("https://www.auto-data.net/en/bmw", AUTO_DATA), {}) is None


def test_snapshot_gets_the_fingerprint_and_version():
    reg = ParserRegistry.from_yaml()
    reg.read(_page("https://www.km77.com/coches/x/datos", KM77, snapshot_id="s1"), {})
    h, key = reg.snapshots["s1"]
    assert key == "km77@v1" and len(h) == 16


def test_zero_streak_is_counted_and_reset():
    reg = ParserRegistry.from_yaml()
    empty = "<html><body><p>nothing</p></body></html>"
    for i in range(3):
        assert reg.read(_page(f"https://www.km77.com/{i}", empty), {}) is None
    assert registry.STREAKS["km77"] == 3 and reg.streaks["km77@v1"].zeros == 3
    reg.read(_page("https://www.km77.com/ok", KM77), {})
    st = reg.streaks["km77@v1"]
    assert registry.STREAKS["km77"] == 0 and st.reset and st.zeros == 0
    assert reg.stats  # site_reader_stats still counted


def test_legacy_reader_name_still_stamps_version_1():
    class R:
        reader = "site:km77"

    assert stamp.reader(R(), None)["producer_version"] == "km77@v1"
