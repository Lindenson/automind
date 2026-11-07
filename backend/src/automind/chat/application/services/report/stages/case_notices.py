"""Stage case_notices: what is said once about the cars themselves — a generation on sale for under two years has no
reliability history (and its "reliability: minimum not reached" is dropped), a car not sold in Spain or the EU
takes its data from its market and its price only from a European source (spec 009 FR-009)."""

from __future__ import annotations

from automind.chat.application.services.report.blocks.notice import Notice, notice
from automind.chat.application.services.report.contracts import KeyedCars, LoadedCar, ReportWording
from automind.chat.application.services.report.facts.car import new_price, short_name
from automind.chat.domain.assessment.metrics import new_generation_since
from automind.shared.vehicle import markets


def car_notices(keyed: KeyedCars, year: int | None, notices: list[Notice], lang: str,
                words: ReportWording) -> None:  # fmt: skip
    """`notices` in place: the young generations' reliability gaps dropped, the generation and market notes added."""
    young = {x.key for x, car in keyed if new_gen(car, year)}
    notices[:] = [n for n in notices if not (n.get("area") == "reliability" and n.get("car_key") in young)]
    notices += [notice(words.t("new_generation", lang, car=short_name(car["variant"]), year=since), "info")
                for _, car in keyed if (since := new_gen(car, year)) is not None]  # fmt: skip
    for x, car in keyed:
        key = markets.abroad_note(x.market, new_price(car) is not None)
        if key is not None:
            text = words.t(key, lang, car=short_name(car["variant"]), market=words.market_name(x.market, lang))
            notices.append(notice(text, "info", car_key=x.key))


def new_gen(car: LoadedCar, year: int | None) -> int | None:
    """The first year of a generation on sale for under two years, else None."""
    return new_generation_since(getattr(car["variant"], "generation_years_from", None), year)
