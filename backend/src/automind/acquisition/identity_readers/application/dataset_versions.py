"""Registered versions of a model from the open datasets (spec 011 identity reader `dataset_versions`).

`DatasetVersions.run` reads offline first: the EEA CO2 groups stored with the gold of the model's catalogue
variants, then the dataset rows cached for the make. Only when neither has the model, one bounded live query of the
make, cached for the dataset's refresh period (an empty or failed answer for a day). The groups become versions by
`domain.registered.group`.

Errors: never raises. `IdentityStoreUnavailable` and any failure of the live query are logged and give an empty list
(the question is asked without these options); a failed live query is cached as empty, so it is not waited for again
until tomorrow.
"""

from __future__ import annotations

import asyncio
import logging

from automind.acquisition.gold.domain.config import MatchCfg
from automind.acquisition.identity_readers.application.ports import IdentityStoreUnavailable, LiveRows, VersionBook
from automind.acquisition.identity_readers.domain.registered import (
    IdRow,
    RegisteredVersion,
    VersionLimits,
    group,
    id_row,
)

log = logging.getLogger(__name__)
EMPTY_DAYS = 1.0  # an empty or failed answer is retried the next day


class DatasetVersions:
    """The registered versions of a model: stored gold, then the cache, then one live query."""

    def __init__(self, book: VersionBook, live: LiveRows | None, limits: VersionLimits, match: MatchCfg,
                 refresh_days: float) -> None:  # fmt: skip
        self._book = book
        self._live = live
        self._limits = limits
        self._match = match
        self._refresh_days = refresh_days

    async def run(self, make: str, model: str, fuel: str | None = None,
                  year_from: int | None = None) -> list[RegisteredVersion]:  # fmt: skip
        """Distinct registered versions of `make` `model` (`fuel`, from `year_from`, the generation's first year:
        the datasets do not name generations), newest first; empty when none is known or the store fails."""
        try:
            found = self._group(await self._book.stored(make, model), make, model, fuel, year_from, 1)
            if found:
                return found
            rows = await self._book.cached(make)
            if rows is None:
                rows = await self._ask_live(make)
            return self._group(rows, make, model, fuel, year_from, self._limits.min_registrations)
        except IdentityStoreUnavailable:
            log.warning("dataset_versions.failed make=%s model=%s", make, model, exc_info=True)
            return []

    async def _ask_live(self, make: str) -> list[IdRow]:
        if self._live is None:
            return []
        try:
            async with asyncio.timeout(self._limits.timeout_s):
                rows = [id_row(r) for r in await self._live(make)]
        except Exception:  # noqa: BLE001 - the datasets only add options; any failure of the query is "no rows"
            log.warning("dataset_versions.live_failed make=%s", make, exc_info=True)
            await self._book.cache(make, [], EMPTY_DAYS)
            return []
        await self._book.cache(make, rows, self._refresh_days if rows else EMPTY_DAYS)
        return rows

    def _group(self, rows: list[IdRow], make: str, model: str, fuel: str | None, year_from: int | None,
               min_registrations: int) -> list[RegisteredVersion]:  # fmt: skip
        return group(rows, make, model, fuel=fuel, year_from=year_from, aliases=self._match.aliases,
                     strip_words=self._match.strip_words, min_registrations=min_registrations)  # fmt: skip
