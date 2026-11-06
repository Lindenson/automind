"""The v1 site readers as they were before parser specifications (spec 003 FR-009, FR-010; research R6).

Kept only as the reference of the v1 equivalence test (spec 011 T080, FR-015): one generic reader of label/value
pairs configured per site in config/site_readers.yaml. The live engine reads with the versioned parser
specifications (`parsing/registry.py` + `parsing/interpreter.py`); `value_and_unit` moved to the interpreter.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from selectolax.lexbor import LexborHTMLParser

from automind.acquisition.parsing.interpreter import value_and_unit
from automind.shared.contracts.site_readers import ReadingRow, SiteReading

__all__ = ["MIN_ROWS", "read_pairs", "value_and_unit"]
MIN_ROWS = 3


def _norm(label: str) -> str:
    return " ".join(label.lower().replace(":", " ").split())


def _pairs(html: str, layout: str) -> Iterator[tuple[str, str]]:
    tree = LexborHTMLParser(html)
    if layout == "divrow":
        for r in tree.css("div.row"):
            p, v = r.css_first("div.par"), r.css_first("div.val")
            if p is not None and v is not None:
                yield p.text(strip=True), v.text(separator=" ", strip=True)
        return
    for tr in tree.css("tr"):
        cells = tr.css("th, td")
        if len(cells) == 2:
            yield cells[0].text(strip=True), cells[1].text(separator=" ", strip=True)


def read_pairs(html: str, conf: Mapping[str, Any], reader_id: str) -> SiteReading | None:
    labels = {_norm(k): v for k, v in (conf.get("labels") or {}).items()}
    rows: list[ReadingRow] = []
    seen: dict[str, str] = {}
    ambiguous = False
    for label, value in _pairs(html, str(conf.get("pairs", "table"))):
        key = _norm(label)
        spec = labels.get(key) or next((s for k, s in labels.items() if s.get("prefix") and key.startswith(k)), None)
        if spec is None or not value or value in ("-", "No disponible"):
            continue
        parsed = value_and_unit(value, spec)
        if parsed is None:
            continue
        attr = str(spec["attribute"])
        if attr in seen:
            ambiguous = ambiguous or seen[attr] != parsed[0]
            continue  # first occurrence wins (the variant's own table comes first)
        seen[attr] = parsed[0]
        rows.append(ReadingRow(attr, parsed[0], parsed[1], f"{label} {value}"))
    if len(rows) < MIN_ROWS:
        return None
    return SiteReading(reader=f"site:{reader_id}", rows=rows, ambiguous=ambiguous)
