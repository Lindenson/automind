"""Spec 011 T085: the layouts and field kinds of the fixed interpreter beyond the v1 tables (dl, css, JSON-LD)."""

from __future__ import annotations

from pathlib import Path

from automind.acquisition.parsing.readers import interpreter
from automind.acquisition.parsing.readers.spec import ParserSpec

FIX = Path(__file__).resolve().parents[3] / "fixtures" / "html"
FIELDS = [
    {"attribute": "max_power", "label": "potencia", "prefer_unit": "kW"},
    {"attribute": "max_torque", "label": "par motor"},
    {"attribute": "curb_mass", "label": "masa en orden de marcha"},
    {"attribute": "top_speed", "label": "velocidad punta"},
]


def _spec(**over) -> ParserSpec:
    d = {"reader": "km77", "version": 2, "domains": ["km77.com"], "layout": "dl", "fields": FIELDS}
    d.update(over)
    return ParserSpec.model_validate(d)


def test_dl_layout_reads_the_redesign():
    got = interpreter.read(_spec(), (FIX / "redesign" / "km77_a.html").read_text(encoding="utf-8"))
    assert got is not None and got.reader == "km77@v2"
    rows = {r.attribute: (r.raw_value, r.raw_unit) for r in got.rows}
    assert rows == {"max_power": ("140", "kW"), "max_torque": ("400", "Nm"), "curb_mass": ("1.615", "kg"),
                    "top_speed": ("238", "km/h")}  # fmt: skip
    assert next(r for r in got.rows if r.attribute == "max_power").excerpt == "Potencia 190 CV / 140 kW"


def test_css_layout_and_css_field():
    html = """<div class="spec"><span class="k">Potencia</span><b class="v">190 CV / 140 kW</b></div>
              <div class="spec"><span class="k">Par motor</span><b class="v">400 Nm</b></div>
              <div class="spec"><span class="k">Masa en orden de marcha</span><b class="v">1.615 kg</b></div>
              <p class="vmax">238 km/h</p>"""
    fields = [*FIELDS[:3], {"attribute": "top_speed", "css": "p.vmax"}]
    spec = _spec(layout="css", row_css="div.spec", label_css="span.k", value_css="b.v", fields=fields)
    got = interpreter.read(spec, html)
    assert got is not None
    assert [(r.attribute, r.raw_value) for r in got.rows] == [
        ("max_power", "140"), ("max_torque", "400"), ("curb_mass", "1.615"), ("top_speed", "238")]  # fmt: skip


def test_jsonld_fields():
    html = """<script type="application/ld+json">{"@context": "https://schema.org", "@graph": [
        {"@type": "Car", "vehicleEngine": {"enginePower": {"value": 140, "unitCode": "KWT"}},
         "weight": {"value": "1615"}, "speed": [{"value": 238}]}]}</script>
        <script type="application/ld+json">not json</script>"""
    fields = [{"attribute": "max_power", "jsonld": "vehicleEngine.enginePower.value", "unit": "kW"},
              {"attribute": "curb_mass", "jsonld": "weight.value", "unit": "kg"},
              {"attribute": "top_speed", "jsonld": "speed.value", "unit": "km/h"},
              {"attribute": "max_torque", "jsonld": "vehicleEngine.torque.value", "unit": "Nm"}]  # fmt: skip
    got = interpreter.read(_spec(layout="table", fields=fields), html)
    assert got is not None
    assert [(r.attribute, r.raw_value, r.raw_unit, r.excerpt) for r in got.rows] == [
        ("max_power", "140", "kW", "value 140"), ("curb_mass", "1615", "kg", "value 1615"),
        ("top_speed", "238", "km/h", "value 238")]  # fmt: skip


def test_too_few_rows_is_no_reading_but_rows_are_counted():
    html = "<dl><dt>Potencia</dt><dd>140 kW</dd></dl>"
    assert interpreter.read(_spec(), html) is None
    assert len(interpreter.read_rows(_spec(), html).rows) == 1
