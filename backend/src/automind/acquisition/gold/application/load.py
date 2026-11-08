"""Load gold values from open datasets and the reference set (spec 011 T023, FR-003).

`GoldLoad.run(name, variants)`: the named source harvests its gold for the variants (a dataset: its rows matched to
each variant by `domain.match`; the reference set: the entries naming a variant), then the load is recorded and the
gold of each (dataset, variant) replaces the previous load — a variant without gold loses the old values of that
dataset. `dry_run` writes nothing.

Errors: an unknown source name raises `ValueError`; the source's errors (`ports.DatasetReader`) and
`GoldStoreUnavailable` pass through — the caller decides (the CLI goes on with the next dataset).
"""

from __future__ import annotations

from collections.abc import Mapping

from automind.acquisition.gold.application.ports import (
    DatasetReader,
    GoldBook,
    GoldSource,
    Harvest,
    ReferenceSet,
)
from automind.acquisition.gold.domain.config import GoldRules, MatchCfg
from automind.acquisition.gold.domain.match import match, variant_key
from automind.acquisition.gold.domain.records import CandidateVariant, GoldValue
from automind.acquisition.gold.domain.reference import reference_gold
from automind.acquisition.gold.domain.text import norm_text


class GoldLoad:
    """Loads one source's gold into the gold book."""

    def __init__(self, book: GoldBook, sources: Mapping[str, GoldSource]) -> None:
        self._book = book
        self._sources = sources

    @property
    def names(self) -> tuple[str, ...]:
        """The sources this load knows, in their load order."""
        return tuple(self._sources)

    async def run(self, name: str, variants: list[CandidateVariant], dry_run: bool = False) -> list[GoldValue]:
        """Harvest, record the load, replace each variant's gold; returns the gold written (or that would be)."""
        source = self._sources.get(name)
        if source is None:
            raise ValueError(f"unknown dataset {name!r}")
        harvest = await source.harvest(variants)
        if not dry_run:
            await self._book.record_load(harvest.info, harvest.rows_read, len({g.variant_id for g in harvest.gold}))
            await self._replace(harvest, variants)
        return harvest.gold

    async def _replace(self, harvest: Harvest, variants: list[CandidateVariant]) -> None:
        per: dict[str, list[GoldValue]] = {v.id: [] for v in variants}
        for g in harvest.gold:
            per.setdefault(g.variant_id, []).append(g)
        for variant_id, values in per.items():
            await self._book.replace(harvest.info.id, variant_id, values)


class DatasetGold:
    """An open dataset as a gold source: the variants' makes read once, every variant matched to the rows."""

    def __init__(self, reader: DatasetReader, cfg: MatchCfg) -> None:
        self._reader = reader
        self._cfg = cfg

    async def harvest(self, variants: list[CandidateVariant]) -> Harvest:
        """The dataset's gold for the variants."""
        rows = await self._reader.rows(sorted({norm_text(v.make).upper() for v in variants}))
        info = self._reader.info()
        gold = [g for v in variants for g in match(rows, variant_key(v, self._cfg), self._cfg, dataset_id=info.id)]
        return Harvest(info, gold, len(rows))


class ReferenceGold:
    """The reference set as a gold source."""

    def __init__(self, reference: ReferenceSet, rules: GoldRules) -> None:
        self._reference = reference
        self._rules = rules

    async def harvest(self, variants: list[CandidateVariant]) -> Harvest:
        """The reference set's gold for the variants it names."""
        entries = self._reference.entries()
        return Harvest(self._reference.info(), reference_gold(entries, variants, self._rules), len(entries))
