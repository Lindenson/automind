"""The items of a non-spec area that a page supports (spec 002 FR-019, 004 FR-005, 006 US6, FR-022): only an item
whose excerpt literally occurs in the page is kept, numbers are read with the sense rules, and each kept item
becomes a row (`rows`). `ExcerptCounter` counts what was kept and what was not; `area_rows` dispatches by area."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from automind.acquisition.domain import sense_ev
from automind.acquisition.parsing.extraction.contracts import MARKET_POSITION, NETWORK_ES, WARRANTIES
from automind.acquisition.parsing.extraction.extract import excerpt_in_doc
from automind.acquisition.pipeline.domain import rows as r
from automind.acquisition.pipeline.domain.used_prices import used_prices
from automind.acquisition.pipeline.domain.written import iso_date, number, whole
from automind.shared.evidence import sense

if TYPE_CHECKING:
    from pydantic import BaseModel

    from automind.acquisition.parsing.extraction.contracts import (
        DepreciationItems,
        IssueItems,
        MaintenanceItems,
        ManufacturerEntry,
        ManufacturerFacts,
        ReviewItems,
        UsedPriceItems,
    )
    from automind.acquisition.pipeline.domain.variant import VariantFacts


class ExcerptCounter:
    """Counts the excerpt checks of one page's items."""

    def __init__(self, doc_text: str) -> None:
        self.doc_text, self.accepted, self.rejected = doc_text, 0, 0

    def ok(self, excerpt: str, must: str | None = None) -> bool:
        """The excerpt occurs in the page (and contains `must`); counted either way."""
        good = excerpt_in_doc(excerpt, self.doc_text, must)
        self.accepted += good
        self.rejected += not good
        return good


def area_rows(v: VariantFacts, area: str, url: str, title: str, out: BaseModel, k: ExcerptCounter,
              rates: dict[str, float], car_year: int | None) -> list[r.PageRow]:  # fmt: skip
    """The rows of one extraction of a non-spec area (`url`/`title`: the page, for brand facts); another market's
    service schedule (e.g. Malaysia) gives none and counts every item rejected."""
    if area == "maintenance" and not sense.market_fits(url, area).ok:
        k.rejected += len(cast("MaintenanceItems", out).items)
        return []
    if area == "maintenance":
        return maintenance(v, cast("MaintenanceItems", out), k)  # the area's schema (extract.schema_for)
    if area == "reviews":
        return reviews(v, cast("ReviewItems", out), k)
    if area in ("reliability", "used_issues"):
        return issues(v, area, cast("IssueItems", out), k)
    if area == "manufacturer":
        return brand_facts(v, url, title, cast("ManufacturerFacts", out), k)
    if area == "used_price":
        return list(used_prices(v, cast("UsedPriceItems", out), k, rates, car_year=car_year))
    if area == "depreciation":
        return retention(v, cast("DepreciationItems", out), k)
    return []


def maintenance(v: VariantFacts, out: MaintenanceItems, k: ExcerptCounter) -> list[r.PageRow]:
    """Schedule items with their intervals and sourced costs."""
    return [r.MaintenanceRow(variant_id=v.id, item=it.item[:200], interval_km=interval_km(it.interval_km),
                             interval_months=interval_months(it.interval_months, it.excerpt),
                             cost_eur=number(it.cost_eur), cost_basis="SOURCED", excerpt=it.excerpt)
            for it in out.items if k.ok(it.excerpt)]  # fmt: skip


def interval_km(raw: str | None) -> int | None:
    """Service interval in km (sense rule: "16" next to "thousand km" is 16,000 km)."""
    return sense.interval_km(whole(raw))


def interval_months(raw: str | None, excerpt: str = "") -> int | None:
    """Interval in months (sense rule: "every 5 years" extracted as 5 is 60 months)."""
    return sense.interval_months(whole(raw), excerpt)


def reviews(v: VariantFacts, out: ReviewItems, k: ExcerptCounter) -> list[r.PageRow]:
    """Pros and cons of expert and owner reviews."""
    return [r.ReviewRow(variant_id=v.id, polarity=it.polarity, tag=it.tag, reviewer=it.reviewer, text=it.text[:300],
                        excerpt=it.excerpt)
            for it in out.items if k.ok(it.excerpt)]  # fmt: skip


def issues(v: VariantFacts, area: str, out: IssueItems, k: ExcerptCounter) -> list[r.PageRow]:
    """Known issues of the car, then reliability statistics (a statistic's excerpt must contain its value)."""
    rows: list[r.PageRow] = [
        r.IssueRow(variant_id=v.id, component=it.component[:120], description=it.description, age_from=it.age_from,
                   age_to=it.age_to, mileage_from=it.mileage_from, mileage_to=it.mileage_to,
                   severity_hint=it.severity_hint, excerpt=it.excerpt, area=area)
        for it in out.issues if k.ok(it.excerpt)
    ]  # fmt: skip
    rows += [r.ReliabilityRow(variant_id=v.id, source=st.source[:120], metric=st.metric, value=st.value[:80],
                              year=st.year, excerpt=st.excerpt)
             for st in out.stats if k.ok(st.excerpt, st.value)]  # fmt: skip
    return rows


def brand_fact_ok(f: ManufacturerEntry) -> tuple[bool, float | None]:
    """Spec 006 US6: a network count only next to a network word, a warranty only with plausible years."""
    value = f.value_num
    if f.fact_type == NETWORK_ES:
        c = sense_ev.count_context(value, f.excerpt)
        return c.ok, c.value
    if f.fact_type in WARRANTIES:
        w = sense_ev.warranty_check(f.fact_type, f.excerpt)
        return w.ok, (w.value or {}).get("years")
    return True, value


def brand_facts(v: VariantFacts, url: str, title: str, out: ManufacturerFacts, k: ExcerptCounter) -> list[r.PageRow]:
    """Facts about the make; a fact with a number keeps it only when the excerpt contains it."""
    rows: list[r.PageRow] = []
    for f in out.facts:
        fits, value = brand_fact_ok(f)
        if not fits:
            k.rejected += 1
            continue
        if k.ok(f.excerpt, must=f"{value:g}" if value is not None else None):
            rows.append(r.BrandFactRow(make=v.make, fact_type=f.fact_type, text=f.text,
                                       positioning=f.positioning if f.fact_type == MARKET_POSITION else None,
                                       value_num=value, year=f.year, excerpt=f.excerpt, url=url,
                                       source_name=title[:200]))  # fmt: skip
    return rows


def retention(v: VariantFacts, out: DepreciationItems, k: ExcerptCounter) -> list[r.PageRow]:
    """Residual values (spec 004 FR-005): verbatim excerpt with the number, 1–10 years, 5–100% left."""
    rows: list[r.PageRow] = []
    for p in out.points:
        share = float(p.share_pct) / 100 if p.share_pct is not None else None
        value = p.share_pct if p.share_pct is not None else p.eur
        if value is None or not 1 <= int(p.years) <= 10 or (share is not None and not 0.05 <= share <= 1.0):
            k.rejected += 1
            continue
        if k.ok(p.excerpt, must=f"{value:g}" if share is None else None):
            eur = float(p.eur) if share is None and p.eur else None
            quoted = iso_date(p.quoted_on)
            rows.append(r.RetentionRow(variant_id=v.id, years=int(p.years), share=share, eur=eur, market=p.market,
                                       quoted_on=quoted, basis="SOURCED", excerpt=p.excerpt[:600]))  # fmt: skip
    return rows
