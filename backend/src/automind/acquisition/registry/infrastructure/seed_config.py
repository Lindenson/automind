"""What the seed and the hard limits read of the owner's configuration: the deny-list and favourites of
`config/sources.yaml`, and the 009 survey (`config/registry_seed_survey.yaml`, a YAML list, not a mapping)."""

from __future__ import annotations

import yaml

from automind.acquisition.registry.domain.seed_rules import Favourite, SurveyEntry
from automind.shared.infrastructure.config.loader import config_dir, load_yaml

SURVEY = "registry_seed_survey.yaml"


def denylist() -> tuple[str, ...]:
    """The deny-listed domains, lower case."""
    return tuple(str(x).lower() for x in load_yaml("sources.yaml").get("denylist") or [])


def favourites() -> list[Favourite]:
    """The owner's favourite sources."""
    return [Favourite.from_mapping(f) for f in load_yaml("sources.yaml").get("favourites") or []]


def survey() -> list[SurveyEntry]:
    """The sites of the 009 survey."""
    data = yaml.safe_load((config_dir() / SURVEY).read_text(encoding="utf-8"))
    return [SurveyEntry.from_mapping(e) for e in data or []]
