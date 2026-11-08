"""Fixed interpreter of parser specifications (spec 011 US4, research R10). Pure.

Written by a person; a `ParserSpec` only fills its parameters (constitution XII, FR-020). Layouts:
`table` (`<tr>` with exactly two cells), `divrow` (`div.row > div.par + div.val`), `dl` (`<dt>` and the next
`<dd>`), `css` (the spec's row, label and value selectors); plus `css` value fields and `jsonld` fields (a dotted
path into the page's `<script type="application/ld+json">`). Values keep their raw text and unit
(`normalise.cell_value`); the domain unit layer normalises them like any other claim. Fewer than `min_rows` matched
rows → no reading (the page falls back to the extractor).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from selectolax.lexbor import LexborHTMLParser, LexborNode

from automind.acquisition.parsing.normalise.cell_value import value_and_unit
from automind.acquisition.parsing.normalise.labels import norm_label
from automind.acquisition.parsing.readers.spec import FieldRule, ParserSpec

Pair = tuple[LexborNode | None, LexborNode | None]


@dataclass(frozen=True)
class Row:
    """One attribute read from the page, raw."""

    attribute: str
    raw_value: str
    raw_unit: str | None
    excerpt: str  # label and value as on the page, so the excerpt validation still applies


@dataclass(frozen=True)
class Reading:
    """The rows one spec version read from one page."""

    reader: str  # the version key, `km77@v1`
    rows: list[Row] = field(default_factory=list)
    ambiguous: bool = False


def read(spec: ParserSpec, html: str, url: str | None = None) -> Reading | None:
    """The page's rows, or None when the page is not the spec's (address) or fewer than `min_rows` rows match."""
    got = read_rows(spec, html, url)
    return got if len(got.rows) >= spec.min_rows else None


def read_rows(spec: ParserSpec, html: str, url: str | None = None) -> Reading:
    """Every matched row, whatever their number (the registry counts fields per page from it)."""
    if not applies(spec, url):
        return Reading(spec.key)
    tree = LexborHTMLParser(html)
    rows: list[Row] = []
    seen: dict[str, str] = {}
    ambiguous = False
    for label, value, rule in _sources(spec, tree):
        if rule is None or not value or value in spec.skip_values:
            continue
        parsed = value_and_unit(value, rule.hints())
        if parsed is None:
            continue
        if rule.attribute in seen:
            ambiguous = ambiguous or seen[rule.attribute] != parsed[0]
            continue  # first occurrence wins (the variant's own table comes first)
        seen[rule.attribute] = parsed[0]
        rows.append(Row(rule.attribute, parsed[0], parsed[1], f"{label} {value}" if label else value))
    return Reading(spec.key, rows, ambiguous)


def applies(spec: ParserSpec, url: str | None) -> bool:
    """Whether the spec reads this address (no `url_patterns` = every page of its domains)."""
    return not spec.url_patterns or url is None or any(re.match(p, url) for p in spec.url_patterns)


def pairs(tree: LexborHTMLParser, spec: ParserSpec) -> Iterator[tuple[str, str]]:
    """(label, value) pairs of the page in document order, as the spec's layout lays them out."""
    for p, v in _LAYOUTS[spec.layout](tree, spec):
        if p is not None and v is not None:
            yield _text(p), _text(v, True)


def _sources(spec: ParserSpec, tree: LexborHTMLParser) -> Iterator[tuple[str, str, FieldRule | None]]:
    """(label, value, rule) in reading order: the layout's pairs, then css fields, then JSON-LD fields."""
    labels: dict[str, FieldRule] = {}
    for f in spec.fields:
        if f.label is not None:
            labels[norm_label(f.label)] = f  # as the v1 readers' label map: a repeated label keeps the last rule
    for label, value in pairs(tree, spec):
        key = norm_label(label)
        rule = labels.get(key) or next((r for k, r in labels.items() if r.prefix and key.startswith(k)), None)
        yield label, value, rule
    for f in spec.fields:
        if f.css is not None:
            el = tree.css_first(f.css)
            if el is not None:
                yield "", _text(el, True), f
    docs = _jsonld_docs(tree) if any(f.jsonld for f in spec.fields) else []
    for f in spec.fields:
        if f.jsonld is not None:
            got = next((v for d in docs if (v := _path(d, f.jsonld)) is not None), None)
            if got is not None:
                yield f.jsonld.rsplit(".", 1)[-1], str(got), f


def _text(n: LexborNode, sep: bool = False) -> str:
    return n.text(separator=" ", strip=True) if sep else n.text(strip=True)


def _table(tree: LexborHTMLParser, spec: ParserSpec) -> Iterator[Pair]:
    for tr in tree.css("tr"):
        cells = tr.css("th, td")
        if len(cells) == 2:
            yield cells[0], cells[1]


def _divrow(tree: LexborHTMLParser, spec: ParserSpec) -> Iterator[Pair]:
    for r in tree.css("div.row"):
        yield r.css_first("div.par"), r.css_first("div.val")


def _dl(tree: LexborHTMLParser, spec: ParserSpec) -> Iterator[Pair]:
    for dt in tree.css("dt"):
        yield dt, _dd_after(dt)


def _css(tree: LexborHTMLParser, spec: ParserSpec) -> Iterator[Pair]:
    for r in tree.css(str(spec.row_css)):
        yield r.css_first(str(spec.label_css)), r.css_first(str(spec.value_css))


def _dd_after(dt: LexborNode) -> LexborNode | None:
    n = dt.next
    while n is not None:
        if n.tag == "dd":
            return n
        if n.tag == "dt":
            return None
        n = n.next
    return None


def _jsonld_docs(tree: LexborHTMLParser) -> list[Any]:
    out: list[Any] = []
    for s in tree.css('script[type="application/ld+json"]'):
        try:
            doc = json.loads(s.text(strip=False) or "null")
        except ValueError:
            continue
        stack = [doc]
        while stack:  # top-level lists and @graph containers hold several objects
            d = stack.pop(0)
            if isinstance(d, list):
                stack[:0] = d
            elif isinstance(d, dict):
                out.append(d)
                if isinstance(d.get("@graph"), list):
                    stack.extend(d["@graph"])
    return out


def _path(doc: Any, path: str) -> Any:
    for part in path.split("."):
        if isinstance(doc, list):
            doc = doc[0] if doc else None
        if not isinstance(doc, dict) or part not in doc:
            return None
        doc = doc[part]
    if isinstance(doc, list):
        doc = doc[0] if doc else None
    return doc if isinstance(doc, (str, int, float)) and not isinstance(doc, bool) else None


_LAYOUTS: dict[str, Callable[[LexborHTMLParser, ParserSpec], Iterator[Pair]]] = {
    "table": _table, "divrow": _divrow, "dl": _dl, "css": _css,
}  # fmt: skip
