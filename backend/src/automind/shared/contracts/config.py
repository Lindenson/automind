"""Static reference data from config/*.yaml, built by infrastructure and passed to the chat and the engine."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

from automind.shared.vehicle.identity import Aliases


class MakeNames(Protocol):
    """The registry of makes (config/makes.yaml, spec 005; implemented by `shared.vehicle.makes.MakeRegistry`): how a
    make is spelt, where it is sold and its sites, and the model a person's words name."""

    names: dict[str, str]  # lower alias / transliteration -> canonical make

    @property
    def makes(self) -> list[str]:
        """The canonical makes."""
        ...

    def new_in_market(self, make: str | None) -> bool:
        """A make new on the Spanish market (its used prices and reliability are thin)."""
        ...

    def site(self, make: str) -> str | None:
        """The maker's Spanish site."""
        ...

    def home(self, make: str | None) -> str | None:
        """The market the make comes from, None when not recorded."""
        ...

    def sold_in_spain(self, make: str | None) -> bool:
        """A make with a Spanish site; a make not in the registry is not known not to be."""
        ...

    def site_on(self, make: str, market: str) -> str | None:
        """The maker's site on a market."""
        ...

    def canonical(self, make: str | None) -> str | None:
        """The make in the registry's spelling, None when unknown."""
        ...

    def make_of_url(self, url: str) -> str | None:
        """The make whose site the URL is on."""
        ...

    def is_home_page(self, url: str) -> bool:
        """The maker's home or country page: it names the make, not a model."""
        ...

    def match_make(self, text: str | None) -> str | None:
        """The make the text names, in any script."""
        ...

    def match_model(self, text: str, known: Iterable[str]) -> str | None:
        """The known model the text names (any script), or None when no model is clearly ahead."""
        ...


@dataclass(frozen=True)
class Reference:
    """Static reference data from config/*.yaml, loaded by infrastructure and passed in."""

    aliases: Aliases
    generations: dict[str, list[tuple[str, int | None, int | None]]]
    questions: dict[str, str]
    prompts: dict[str, str]
    queries: dict[str, list[str]]
    criteria: Any = None  # domain.criteria.CriteriaModel (config/criteria.yaml)
    rates: dict[str, Any] | None = None  # config/rates.yaml (TCO)
    favourite_queries: dict[str, str] = field(default_factory=dict)  # area -> template with {sites}
    search: dict[str, Any] = field(default_factory=dict)  # config/search.yaml
    favourites: list[dict[str, Any]] = field(default_factory=list)  # config/sources.yaml favourites
    manufacturer_sites: dict[str, str] = field(default_factory=dict)  # make -> official ES site
    plausibility: dict[str, Any] = field(default_factory=dict)  # config/plausibility.yaml
    feasibility: dict[str, Any] = field(default_factory=dict)  # config/feasibility.yaml
    insights: dict[str, Any] = field(default_factory=dict)  # config/insights.yaml (spec 004)
    layouts: dict[str, Any] = field(default_factory=dict)  # config/report_layouts.yaml (spec 004)
    explainers: dict[str, Any] = field(default_factory=dict)  # config/tech_explainers.yaml (spec 004)
    questions_i18n: dict[str, Any] = field(default_factory=dict)  # config/questions.yaml v2 (spec 005)
    makes: MakeNames | None = None  # config/makes.yaml (spec 005)
    regions: dict[str, Any] = field(default_factory=dict)  # config/regions.yaml (spec 005)
    profile_defaults: dict[str, Any] = field(default_factory=dict)  # config/profile_defaults.yaml (spec 007)
    gearboxes: dict[str, list[str]] = field(default_factory=dict)  # "Make|Model|generation" -> gearboxes sold new
    outcome: dict[str, Any] = field(default_factory=dict)  # config/outcome.yaml (spec 010 US1)
    insight: dict[str, Any] = field(default_factory=dict)  # config/insight.yaml (spec 010 US3)
    registry: dict[str, Any] = field(default_factory=dict)  # config/registry.yaml (spec 010 US6-US8)
