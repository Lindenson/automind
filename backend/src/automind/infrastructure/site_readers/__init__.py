"""Deterministic table readers for favourite spec sites (spec 003 FR-009, FR-010; research R6).

One generic reader of label/value pairs, configured per site in config/site_readers.yaml (layout and
label → canonical attribute map). It returns raw values with the row text as excerpt; units are
normalised by the domain unit layer like any other claim. A reader runs only for favourites whose
`reader` is set and whose `tos_checked` date is set (the operator reviewed the site's terms of use).
Unknown layouts return None, so the page falls back to the LLM extractor.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from typing import Any

from selectolax.lexbor import LexborHTMLParser

from automind.application.ports import Page, ReadingRow, SiteReading
from automind.domain.evidence import domain_of

_NUM = r"(\d[\d.,]*)"
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


def value_and_unit(text: str, spec: Mapping[str, Any]) -> tuple[str, str | None] | None:
    """Raw number and unit from a cell like '190 CV / 140 kW' or '1540 kg3395 lbs.'."""
    t = " ".join(text.replace("\xa0", " ").split())
    t = re.sub(r"\b(cm|m|dm) ([23])\b", r"\1\2", t)  # "cm<sup>3</sup>" read with a separator
    if spec.get("text"):
        return t, None
    if pu := spec.get("prefer_unit"):
        m = re.search(_NUM + r"\s*" + re.escape(str(pu)), t, re.I)
        if m:
            return m.group(1), str(spec.get("unit") or pu)
    if re.match(r"\s*" + _NUM + r"\s*[-–]\s*\d", t):
        return t, spec.get("unit")  # a range ("4.2-4.5 l/100 km"): the unit layer rejects it as not one value
    m = re.match(r"\s*" + _NUM + r"\s*([A-Za-z³²µ°%]+(?:/[0-9]*\s?[A-Za-z]*)?)?", t)
    if not m:
        return None
    unit = spec.get("unit") or ((m.group(2) or "").strip(". ") or None)
    return m.group(1), (str(unit) if unit else None)


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


log = logging.getLogger(__name__)
ALERT_STREAK = 5
STREAKS: dict[str, int] = {}  # reader -> pages in a row with nothing found (exported to Prometheus, spec 010)


class Registry:
    """Domain → reader for enabled favourites; counts ok/failed/ambiguous per site and day."""

    def __init__(self, conf: Mapping[str, Any], favourites: list[dict[str, Any]]) -> None:
        self.conf = {k: v for k, v in conf.items() if k != "version"}
        self.enabled: dict[str, str] = {}
        for f in favourites:
            rid = f.get("reader")
            if rid and f.get("tos_checked") and rid in self.conf:
                for d in self.conf[rid].get("domains") or [f["domain"]]:
                    self.enabled[str(d)] = str(rid)
        self.stats: dict[tuple[str, str], dict[str, int]] = {}
        self.fail_streak: dict[str, int] = {}  # pages in a row where the reader found nothing

    def reader_for(self, url: str) -> str | None:
        dom = domain_of(url)
        return next((r for d, r in self.enabled.items() if dom == d or dom.endswith("." + d)), None)

    def read(self, page: Page, target: dict[str, Any]) -> SiteReading | None:
        rid = self.reader_for(page.url)
        if rid is None or not page.html:
            return None
        try:
            out = read_pairs(page.html, self.conf[rid], rid)
        except Exception:  # noqa: BLE001 - a broken page never fails the job
            out = None
        day = datetime.now(UTC).date().isoformat()
        k = (domain_of(page.url), day)
        s = self.stats.setdefault(k, {"ok": 0, "failed": 0, "ambiguous": 0})
        s["failed" if out is None else "ambiguous" if out.ambiguous else "ok"] += 1
        streak = self.fail_streak[k[0]] = self.fail_streak.get(k[0], 0) + 1 if out is None else 0
        STREAKS[k[0]] = streak
        if streak == ALERT_STREAK:  # a redesign breaks label readers silently (reviewer 2026-11-03): say it once
            log.warning("site_reader.broken reader=%s domain=%s pages_in_a_row=%d", rid, k[0], streak,
                        extra={"event": "site_reader.broken", "reader": rid, "domain": k[0]})  # fmt: skip
        return out

    async def flush_stats(self) -> None:
        """Add the counted reads to site_reader_stats (FR-009 failure counts per site, SC-005)."""
        if not self.stats:
            return
        from sqlalchemy.dialects.postgresql import insert  # noqa: PLC0415

        from automind.infrastructure.db import SiteReaderStat, sessionmaker  # noqa: PLC0415

        pending, self.stats = self.stats, {}
        async with sessionmaker()() as s:
            for (domain, day), n in pending.items():
                stmt = insert(SiteReaderStat).values(domain=domain, day=datetime.fromisoformat(day).date(), **n)
                await s.execute(stmt.on_conflict_do_update(
                    index_elements=["domain", "day"],
                    set_={k: getattr(SiteReaderStat, k) + stmt.excluded[k] for k in n},
                ))  # fmt: skip
            await s.commit()


def live_readers() -> Registry:
    from automind.infrastructure.config import favourites, load_yaml  # noqa: PLC0415

    return Registry(load_yaml("site_readers.yaml"), favourites())
