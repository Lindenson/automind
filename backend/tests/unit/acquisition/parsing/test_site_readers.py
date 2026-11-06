"""Site readers on trimmed real pages (spec 003 T027/T031; SC-005): rows, units, excerpts, unknown layout."""

from pathlib import Path

import pytest

from automind.acquisition.parsing.legacy import read_pairs, value_and_unit
from automind.acquisition.parsing.registry import ParserRegistry
from automind.shared.contracts.web import Page
from automind.shared.infrastructure.config.loader import load_yaml
from automind.shared.vehicle import specs

FIX = Path(__file__).resolve().parents[3] / "fixtures" / "html"
CONF = load_yaml("site_readers.yaml")


def rows(reader, name):
    out = read_pairs((FIX / name).read_text(encoding="utf-8"), CONF[reader], reader)
    assert out is not None
    values = {}
    for r in out.rows:
        try:
            values[r.attribute] = specs.normalize(specs.ATTRS[r.attribute], r.raw_value, r.raw_unit)
        except Exception:  # noqa: BLE001 - e.g. a consumption range: rejected by the unit layer, as in research
            continue
    return out, values


def test_km77():
    out, v = rows("km77", "km77_bmw_520d_g30.html")
    assert v["max_power"] == 140 and v["max_torque"] == 400 and v["curb_mass"] == 1615
    assert v["claimed_0_100"] == 7.7 and v["top_speed"] == 238 and v["displacement"] == 1995
    assert v["boot_volume"] == 530 and v["seats"] == 5 and v["drivetrain"] == "RWD"
    assert v["bore"] == 84 and v["stroke"] == 90
    row = next(r for r in out.rows if r.attribute == "max_power")
    assert row.excerpt == "Potencia máxima 190 CV / 140 kW"


def test_ultimatespecs():
    out, v = rows("ultimatespecs", "ultimatespecs_bmw_g30_520d.html")
    assert v["max_power"] == 140 and v["max_torque"] == 400 and v["curb_mass"] == 1635
    assert v["claimed_0_100"] == 7.5 and v["top_speed"] == 235 and v["displacement"] == 1995
    assert v["drivetrain"] == "RWD"


def test_auto_data():
    out, v = rows("auto_data", "auto_data_bmw_g30_520d.html")
    assert abs(v["max_power"] - 139.7) < 0.2  # "190 Hp" on auto-data is metric (PS)
    assert v["max_torque"] == 400 and v["curb_mass"] == 1540 and v["claimed_0_100"] == 7.7
    assert v["top_speed"] == 238 and v["boot_volume"] == 530 and v["ground_clearance"] == 144


def test_unknown_layout_returns_none():
    assert read_pairs("<html><body><p>no tables here</p></body></html>", CONF["km77"], "km77") is None


def test_conflicting_duplicate_label_marks_ambiguous():
    html = (FIX / "km77_bmw_520d_g30.html").read_text(encoding="utf-8")
    html = html.replace("</body>", "<table><tr><td>Potencia máxima</td><td>265 CV / 195 kW</td></tr></table></body>")
    out = read_pairs(html, CONF["km77"], "km77")
    assert out.ambiguous
    assert next(r for r in out.rows if r.attribute == "max_power").raw_value == "140"  # first table wins


@pytest.mark.parametrize(
    ("text", "spec", "expected"),
    [
        ("190 CV / 140 kW", {"prefer_unit": "kW"}, ("140", "kW")),
        ("1540 kg3395 lbs.", {"prefer_unit": "kg"}, ("1540", "kg")),
        ("1.615 kg", {}, ("1.615", "kg")),
        ("7.7 sec", {}, ("7.7", "sec")),
        ("190 Hp @ 4000 rpm.", {"unit": "PS"}, ("190", "PS")),
        ("Trasera", {"text": True}, ("Trasera", None)),
    ],
)
def test_value_and_unit(text, spec, expected):
    assert value_and_unit(text, spec) == expected


def test_registry_runs_only_for_reviewed_favourites():
    favs = [{"domain": "km77.com", "reader": "km77", "tos_checked": "2026-11-02"},
            {"domain": "ultimatespecs.com", "reader": "ultimatespecs", "tos_checked": None}]  # fmt: skip
    reg = ParserRegistry.from_yaml(favs)
    html = (FIX / "km77_bmw_520d_g30.html").read_text(encoding="utf-8")
    assert reg.read(Page(url="https://www.km77.com/x/datos", title="t", text="", html=html), {}) is not None
    us = (FIX / "ultimatespecs_bmw_g30_520d.html").read_text(encoding="utf-8")
    assert reg.read(Page(url="https://www.ultimatespecs.com/y", title="t", text="", html=us), {}) is None
    assert reg.read(Page(url="https://www.km77.com/x/datos", title="t", text="cached, no html"), {}) is None
