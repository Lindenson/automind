"""Static reference data from config/*.yaml, built by infrastructure and passed to the chat and the engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from automind.domain.identity import Aliases


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
    makes: Any = None  # application.makes.MakeRegistry (config/makes.yaml, spec 005)
    regions: dict[str, Any] = field(default_factory=dict)  # config/regions.yaml (spec 005)
    profile_defaults: dict[str, Any] = field(default_factory=dict)  # config/profile_defaults.yaml (spec 007)
    gearboxes: dict[str, list[str]] = field(default_factory=dict)  # "Make|Model|generation" -> gearboxes sold new
    outcome: dict[str, Any] = field(default_factory=dict)  # config/outcome.yaml (spec 010 US1)
    insight: dict[str, Any] = field(default_factory=dict)  # config/insight.yaml (spec 010 US3)
    registry: dict[str, Any] = field(default_factory=dict)  # config/registry.yaml (spec 010 US6-US8)
