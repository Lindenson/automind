"""Seed the registry (spec 010 US8, T050): the favourites of `config/sources.yaml` and the 009 survey. Idempotent.
(Spec 007's learned domains were seeded once; the rule is gone since spec 011 T124.)

Errors: `RegistryStoreUnavailable` propagates; each part (favourites, survey) is one transaction, so a failed survey
leaves the favourites seeded and the next start completes it."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from automind.acquisition.registry.application.ports import SeedBook
from automind.acquisition.registry.domain.seed_rules import Favourite, SurveyEntry, from_favourite, from_survey


@dataclass(frozen=True)
class SeedSources:
    """What the seed starts from: the owner's favourites, the survey, the deny-list and the mirror families."""

    favourites: Sequence[Favourite]
    survey: Sequence[SurveyEntry]
    deny: Sequence[str]
    families: Mapping[str, Sequence[str]]


class RegistrySeed:
    """The registry's first content over its book."""

    def __init__(self, book: SeedBook, sources: SeedSources) -> None:
        self.book = book
        self.sources = sources

    async def run(self) -> dict[str, int]:
        """Seed what is missing; how many capabilities each part added."""
        s = self.sources
        favourites = [from_favourite(f, s.deny, s.families) for f in s.favourites]
        survey = [from_survey(e, s.deny, s.families) for e in s.survey]
        return {
            "favourites": await self.book.seed(favourites, "seed: config/sources.yaml favourite"),
            "survey": await self.book.seed(survey, "seed: 009 survey (robots and terms)"),
        }

    async def run_if_empty(self) -> dict[str, int] | None:
        """Seed an empty registry; None when it already has sources."""
        return await self.run() if await self.book.is_empty() else None
