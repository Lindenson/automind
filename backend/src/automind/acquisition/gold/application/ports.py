"""The ports of gold's services: the gold book (datasets, values), the catalogue variants gold is loaded for, an open
dataset's reader and the reference set.

Errors: `GoldBook` and `Candidates` raise `GoldStoreUnavailable` when their database fails, with the cause chained;
each write is one transaction, so a failed one leaves the previous load in place. `DatasetReader.rows` reaches an
official open-data API: it raises `SchemaChanged` (gold.infrastructure.loaders) when a pinned column is missing,
`ValueError` for a make name that cannot go into a query, and the HTTP client's errors as they come.
`ReferenceSet.entries` raises `OSError` when the file cannot be read."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from automind.acquisition.gold.domain.records import CandidateVariant, DatasetInfo, DatasetRow, GoldValue, StoredGold
from automind.shared.contracts.json import JsonObject


class GoldStoreUnavailable(RuntimeError):
    """A gold store could not read or write (its database); the cause is chained."""


class GoldBook(Protocol):
    """`gold_datasets` and `gold_values`."""

    async def record_load(self, info: DatasetInfo, rows_read: int = 0, rows_matched: int = 0) -> None:
        """Record a load of the dataset (its time, counts and next refresh)."""
        ...

    async def replace(self, dataset_id: str, variant_id: str, gold: Iterable[GoldValue]) -> int:
        """The dataset's gold of one variant: the newest load replaces the previous one; returns how many."""
        ...

    async def put(self, gold: GoldValue) -> None:
        """One gold value: replaces the value of the same variant, attribute, origin and dataset."""
        ...

    async def stored(self, variant_id: str, include_flagged: bool = False) -> list[StoredGold]:
        """The variant's gold (flagged gold left out unless asked for)."""
        ...

    async def best(self, variant_id: str) -> dict[str, StoredGold]:
        """The best unflagged gold of each attribute of the variant (`choice.best_by_attribute`)."""
        ...


class Candidates(Protocol):
    """The catalogue variants gold may be loaded for."""

    async def variants(self, make: str | None = None, recent: bool = False) -> list[CandidateVariant]:
        """Every variant (of `make`; with `recent`, only those researched in the last 30 days)."""
        ...


class DatasetReader(Protocol):
    """One open dataset, read through its official API."""

    def info(self) -> DatasetInfo:
        """The dataset as a load records it (id with its version, licence, next refresh)."""
        ...

    async def rows(self, makes: list[str]) -> list[DatasetRow]:
        """The dataset's groups of these makes (upper case)."""
        ...


class ReferenceSet(Protocol):
    """The hand-checked reference set."""

    def info(self) -> DatasetInfo:
        """The reference set as a load records it."""
        ...

    def entries(self) -> list[JsonObject]:
        """Its entries that cite sources."""
        ...


@dataclass(frozen=True)
class Harvest:
    """What one source gives for a set of variants: its description, the gold and how many records it read."""

    info: DatasetInfo
    gold: list[GoldValue]
    rows_read: int


class GoldSource(Protocol):
    """A source of gold for catalogue variants (an open dataset or the reference set)."""

    async def harvest(self, variants: list[CandidateVariant]) -> Harvest:
        """The source's gold for these variants."""
        ...
