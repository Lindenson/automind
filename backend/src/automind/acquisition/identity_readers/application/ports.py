"""The ports of the registered-versions reader: the version book (groups stored with gold, dataset rows cached per
make) and the live open-dataset query.

Errors: `VersionBook` raises `IdentityStoreUnavailable` when its database fails, with the cause chained. `LiveRows`
reaches an official open-data API and may fail in any way (network, a changed schema, a slow answer): its caller
treats every failure as "no rows"."""

from __future__ import annotations

from typing import Protocol

from automind.acquisition.gold.domain.records import DatasetRow
from automind.acquisition.identity_readers.domain.registered import IdRow


class IdentityStoreUnavailable(RuntimeError):
    """An identity readers' store could not read or write (its database); the cause is chained."""


class VersionBook(Protocol):
    """The dataset groups known offline: stored with the gold values, or cached per make by a live query."""

    async def stored(self, make: str, model: str) -> list[IdRow]:
        """The EEA groups matched to the model's catalogue variants by the last gold load."""
        ...

    async def cached(self, make: str) -> list[IdRow] | None:
        """The make's dataset rows cached by an earlier live query; None when not cached or expired."""
        ...

    async def cache(self, make: str, rows: list[IdRow], days: float) -> None:
        """Keep the make's rows (an empty list too) for `days`."""
        ...


class LiveRows(Protocol):
    """One live query of an open dataset for a make (`AcqPorts.datasets`)."""

    async def __call__(self, make: str) -> list[DatasetRow]:
        """The dataset's groups of the make."""
        ...
