"""Market-level incentives (spec 006 US5, FR-016; research R11): what is stored. The view the report reads is
`domain.incentives.view` (spec 011 S0); moved from `application/incentives_research.py` (S7).

A fact is stored only with a verbatim excerpt that contains its amount or percent, once per market and key (the
newest reading replaces the older; storage is the `market_facts` port). The status is never stored as truth: it
is recomputed from the dates on read (`domain.incentives.status`), so a programme that ended last week shows as
expired.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from automind.acquisition.pipeline import extract as ex
from automind.application.ports import WebDoc

VERSION = "market@1"
MARKET = "ES"


def _date(raw: str | None) -> date | None:
    try:
        return date.fromisoformat(raw[:10]) if raw else None
    except ValueError:
        return None


def _key(f: Any) -> str:
    return f"{f.key}.{f.region_code.upper()}" if f.key == "subsidy.region" and f.region_code else str(f.key)


def _number_ok(f: Any, doc_text: str) -> bool:
    for n in (f.amount_eur, f.percent):
        if n is not None:
            whole = f"{n:,.0f}"
            forms = {f"{n:g}", whole, whole.replace(",", "."), whole.replace(",", " "), whole.replace(",", "")}
            if not any(x in f.excerpt for x in forms):
                return False
    return ex.excerpt_in_doc(f.excerpt, doc_text)


def accept(out: Any, d: WebDoc) -> tuple[list[dict[str, Any]], int]:
    """The facts of one page worth storing (excerpt in the page, its amount or percent in the excerpt, a
    plausible amount), as rows for the market-facts store; returns (rows, rejected)."""
    rows, rej = [], 0
    for f in getattr(out, "facts", []) or []:
        amount_ok = f.amount_eur is None or 0 < f.amount_eur <= 20000
        if not amount_ok or not _number_ok(f, d.text):
            rej += 1
            continue
        value = {"label": f.label[:120], "text": f.excerpt, "amount_eur": f.amount_eur, "percent": f.percent,
                 "scope": f.scope, "region_code": f.region_code, "powertrains": list(f.powertrains),
                 "url": d.url, "source_name": d.title[:200]}  # fmt: skip
        rows.append({"key": _key(f)[:60], "value": value, "valid_from": _date(f.valid_from),
                     "valid_to": _date(f.valid_to)})  # fmt: skip
    return rows, rej
