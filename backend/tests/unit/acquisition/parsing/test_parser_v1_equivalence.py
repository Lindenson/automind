"""Spec 011 T080 (FR-015, US4 AS-1): every reader of config/site_readers.yaml, migrated to a version-1 parser spec and
run by the fixed interpreter, returns exactly the rows and the `ambiguous` flag of the legacy reader on every fixture
page (and on variations that exercise duplicates, prefixes, skipped values and too few rows)."""

from __future__ import annotations

from pathlib import Path

import pytest

from automind.acquisition.parsing import interpreter
from automind.acquisition.parsing.legacy import read_pairs
from automind.acquisition.parsing.migrate_v1 import migrate_v1
from automind.shared.infrastructure.config.loader import load_yaml

FIX = Path(__file__).resolve().parents[3] / "fixtures" / "html"
READERS = {k: v for k, v in load_yaml("site_readers.yaml").items() if k != "version"}
PAGES = sorted([*FIX.glob("*.html"), *(FIX / "km77_three").glob("*.html")])
EXTRA = {  # hand-made variations of the fixture pages
    "duplicate": "<table><tr><td>Potencia máxima</td><td>265 CV / 195 kW</td></tr>"
    "<tr><td>Horsepower</td><td>300 PS / 221 kW</td></tr></table>",
    "skipped": "<table><tr><td>Par máximo</td><td>-</td></tr><tr><td>Curb Weight:</td><td>No disponible</td></tr>"
    "</table>",
    "empty": "<p>nothing</p>",
}


def _rows(reading):
    if reading is None:
        return None
    return [(r.attribute, r.raw_value, r.raw_unit, r.excerpt) for r in reading.rows], reading.ambiguous


def _pages():
    for p in PAGES:
        html = p.read_text(encoding="utf-8")
        yield p.name, html
        for name, extra in EXTRA.items():
            yield f"{p.name}+{name}", html.replace("</body>", extra + "</body>")
            yield f"{name}+{p.name}", html.replace("<body>", "<body>" + extra, 1)


@pytest.mark.parametrize("reader", sorted(READERS))
def test_v1_spec_reads_what_the_legacy_reader_read(reader):
    conf = READERS[reader]
    spec = migrate_v1(reader, conf)
    seen_rows = 0
    for name, html in _pages():
        legacy = _rows(read_pairs(html, conf, reader))
        ours = _rows(interpreter.read(spec, html))
        assert ours == legacy, f"{reader} on {name}"
        seen_rows += len(legacy[0]) if legacy else 0
    assert seen_rows > 0, f"{reader}: no fixture page exercised the reader"


def test_reading_names_the_version_key():
    spec = migrate_v1("km77", READERS["km77"])
    got = interpreter.read(spec, (FIX / "km77_bmw_520d_g30.html").read_text(encoding="utf-8"))
    assert got is not None and got.reader == "km77@v1"


def test_url_patterns_limit_the_pages():
    spec = migrate_v1("km77", READERS["km77"]).model_copy(
        update={"url_patterns": ["^https://www\\.km77\\.com/coches/"]}
    )
    html = (FIX / "km77_bmw_520d_g30.html").read_text(encoding="utf-8")
    assert interpreter.read(spec, html, "https://www.km77.com/coches/bmw/x/datos") is not None
    assert interpreter.read(spec, html, "https://www.km77.com/foro/123") is None
