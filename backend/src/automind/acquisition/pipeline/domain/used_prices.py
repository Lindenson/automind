"""Editorial used-price ranges (spec 004 FR-022): a range is kept with a verbatim excerpt, plausible numbers in EUR
and a spread of one price, not a whole market; for a car with a model year, a range over several model years (a
whole generation) never stands for one year (seeded issue, chat 8c6a2a58). Every range becomes a row with its
status, accepted or not."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

from automind.acquisition.pipeline.domain.rows import UsedPriceRow
from automind.acquisition.pipeline.domain.written import iso_date
from automind.chat.domain.identification import used

if TYPE_CHECKING:
    from automind.acquisition.pipeline.domain.items import ExcerptCounter
    from automind.acquisition.pipeline.domain.variant import VariantFacts
    from automind.acquisition.pipeline.extract import UsedPriceItems

USED_RANGE_MAX_RATIO = 1.6  # a used-price range wider than this (max / min) is a whole-market spread, not a price
LOWEST_EUR, HIGHEST_EUR = 500, 600_000


def used_prices(v: VariantFacts, out: UsedPriceItems, k: ExcerptCounter, rates: dict[str, float],
                car_year: int | None = None) -> Iterator[UsedPriceRow]:  # fmt: skip
    """One row per range, converted to EUR with `rates`; status ACCEPTED or why not."""
    for p in out.ranges:
        lo, hi = sorted((float(p.min), float(p.max)))
        rate = rates.get(p.currency, 1.0)
        # chat fcf5b3b8: "21 100 € – 93 520 €" for every Land Cruiser of a year is a market spread, not a price
        plausible = LOWEST_EUR <= lo * rate <= hi * rate <= HIGHEST_EUR and hi <= USED_RANGE_MAX_RATIO * lo
        whole = used.whole_generation(p.model_year_from, p.model_year_to, car_year)
        good = not whole and k.ok(p.excerpt) and plausible
        if whole:
            k.rejected += 1
        status = ("ACCEPTED" if good else "REJECTED_OTHER_YEAR" if whole
                  else "REJECTED_IMPLAUSIBLE" if not plausible else "REJECTED_UNSUPPORTED")  # fmt: skip
        yield UsedPriceRow(variant_id=v.id, model_year_from=p.model_year_from, model_year_to=p.model_year_to,
                           min_eur=round(lo * rate), max_eur=round(hi * rate), market=p.market,
                           quoted_on=iso_date(p.quoted_on), excerpt=p.excerpt[:300], status=status)  # fmt: skip
