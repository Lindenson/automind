"""Spec 011 T079: the declarative parser specification (contracts/parser-spec.md) — valid v1 specs parse, every kind
of invalid proposal is listed by `check()` before any gate."""

from __future__ import annotations

import json

import pytest

from automind.acquisition.parsing import spec as ps
from automind.acquisition.parsing.migrate_v1 import migrate_v1
from automind.infrastructure.config import load_yaml

READERS = {k: v for k, v in load_yaml("site_readers.yaml").items() if k != "version"}
SOURCES = {"km77.com": {"access": "ok"}, "ultimatespecs.com": {"access": "ok"}}
DENY = ("auto-data.net", "coches.net")


def _base(**over):
    d = {
        "reader": "km77",
        "version": 2,
        "domains": ["km77.com"],
        "layout": "table",
        "fields": [
            {"attribute": "max_power", "label": "potencia máxima", "prefer_unit": "kW"},
            {"attribute": "max_torque", "label": "par máximo"},
            {"attribute": "curb_mass", "label": "peso"},
        ],
    }
    d.update(over)
    return d


def _errors(data, **kw):
    return ps.check(data, sources=kw.get("sources", SOURCES), denylist=kw.get("denylist", DENY))


@pytest.mark.parametrize("reader", ["km77", "ultimatespecs"])
def test_v1_specs_are_valid(reader):
    spec = migrate_v1(reader, READERS[reader])
    assert spec.version == 1 and spec.reader == reader
    assert _errors(spec) == []
    assert _errors(spec.model_dump(mode="json")) == []  # the stored JSON form as well


def test_auto_data_v1_parses_but_is_deny_listed():
    spec = migrate_v1("auto_data", READERS["auto_data"])
    assert spec.layout == "divrow"
    errs = _errors(spec)
    assert any("deny-list" in e for e in errs)


def test_a_valid_proposal():
    assert _errors(_base()) == []


@pytest.mark.parametrize(
    ("change", "needle"),
    [
        ({"fields": [{"attribute": "warp_factor", "label": "warp"}]}, "unknown attribute"),
        ({"fields": [{"attribute": "max_power", "label": "potencia", "unit": "furlongs"}]}, "unit"),
        ({"fields": [{"attribute": "max_power", "label": "potencia", "prefer_unit": "parsecs"}]}, "unit"),
        ({"fields": [{"attribute": "max_power", "label": "potencia", "extra": 1}]}, "extra"),
        ({"surprise": True}, "extra"),
        ({"fields": [{"attribute": "max_power", "label": "potencia", "css": "td.v"}]}, "exactly one"),
        ({"fields": [{"attribute": "max_power", "label": "a", "jsonld": "vehicleEngine.enginePower.value"}]},
         "exactly one"),
        ({"fields": [{"attribute": "max_power"}]}, "exactly one"),
        ({"layout": "css", "row_css": "div..row", "label_css": "span", "value_css": "b"}, "selector"),
        ({"layout": "css"}, "row_css"),
        ({"url_patterns": ["^https://www\\.km77\\.com/(a+)+$"]}, "nested quantifier"),
        ({"url_patterns": ["^https://www\\.km77\\.com/(x)\\1$"]}, "back-reference"),
        ({"url_patterns": ["^https://www\\.km77\\.com/" + "a" * 200]}, "200"),
        ({"url_patterns": ["https://www\\.km77\\.com/.*"]}, "anchored"),
        ({"url_patterns": ["^(unclosed"]}, "regex"),
        ({"domains": ["auto-data.net"]}, "deny-list"),
        ({"domains": ["unknown.example"]}, "registry"),
        ({"reader": "KM 77"}, "reader"),
        ({"version": 0}, "version"),
        ({"notes": "x" * 501}, "notes"),
        ({"fields": []}, "fields"),
    ],
)  # fmt: skip
def test_invalid_specs_are_listed(change, needle):
    errs = _errors(_base(**change))
    assert errs, f"expected an error for {change}"
    assert any(needle.lower() in e.lower() for e in errs), errs


def test_css_field_needs_css_layout():
    errs = _errors(_base(fields=[{"attribute": "max_power", "css": "td.power"}]))
    assert any("layout" in e for e in errs)


def test_valid_css_layout_and_jsonld_fields():
    d = _base(
        layout="css",
        row_css="div.ficha dl",
        label_css="dt",
        value_css="dd",
        fields=[
            {"attribute": "max_power", "label": "potencia", "prefer_unit": "kW"},
            {"attribute": "top_speed", "css": "span.vmax"},
            {"attribute": "curb_mass", "jsonld": "weight.value", "unit": "kg"},
        ],
    )
    assert _errors(d) == []


def test_same_attribute_twice_needs_different_labels():
    two = [{"attribute": "max_power", "label": "potencia"}, {"attribute": "max_power", "label": "potencia máxima"}]
    assert _errors(_base(fields=two)) == []
    same = [{"attribute": "max_power", "label": "potencia"}, {"attribute": "max_power", "label": "Potencia:"}]
    assert any("twice" in e for e in _errors(_base(fields=same)))


def test_size_limit():
    fields = [{"attribute": "max_power", "label": f"potencia {i} " + "x" * 300} for i in range(60)]
    errs = _errors(_base(fields=fields))
    assert any("20 KB" in e for e in errs)


def test_blocked_or_frozen_source():
    assert any("access" in e for e in _errors(_base(), sources={"km77.com": {"access": "terms_forbid"}}))
    assert any("frozen" in e for e in _errors(_base(), sources={"km77.com": {"access": "ok", "frozen": True}}))


def test_json_text_is_accepted_and_bad_json_is_an_error():
    assert _errors(json.dumps(_base())) == []
    assert _errors("{not json") != []


@pytest.mark.parametrize(
    ("pattern", "safe"),
    [
        ("^https://www\\.km77\\.com/coches/.+/datos$", True),
        ("^https://[a-z.]+/fichas/[0-9]+$", True),
        ("^(a|b)*$", True),
        ("^(a+)+$", False),
        ("^(a*)*b$", False),
        ("^(?:x+y?)+$", False),
        ("^(?P<n>a)(?P=n)$", False),
    ],
)
def test_regex_safety(pattern, safe):
    assert (ps.regex_problem(pattern) is None) is safe
