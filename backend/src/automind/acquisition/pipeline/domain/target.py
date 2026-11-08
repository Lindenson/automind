"""The car a job is about, as the extraction, relevance and validator roles are told it."""

from __future__ import annotations

from automind.acquisition.pipeline.domain.variant import VariantFacts


def target_of(v: VariantFacts, car_year: int | None = None, home: str | None = None) -> str:
    """The car for the extractor, the relevance role and the validator. `home`: what `home_market.home_target` says
    about a car sold only outside Europe (its market, its local name, how its pages label the figures)."""
    years = f" ({v.generation_years_from}–{v.generation_years_to or 'now'})" if v.generation_years_from else ""
    body = f", body {v.body_class.lower()}" if v.body_class else ""
    year = f", the user's car is from ~{car_year}" if car_year else ""
    return f"{v.label}{years}, powertrain {v.powertrain}{body}, {home or 'market ES'}{year}"
