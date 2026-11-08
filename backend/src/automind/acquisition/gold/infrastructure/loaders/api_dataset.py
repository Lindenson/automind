"""One open-data loader as the services' `DatasetReader`: its module's `fetch_rows` and `version` over the dataset's
mapping of `config/gold_datasets.yaml`. Errors are the loader's (`SchemaChanged`, `ValueError`, httpx)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol

import httpx

from automind.acquisition.gold.domain.records import DatasetInfo, DatasetRow
from automind.acquisition.gold.infrastructure.loaders import meta


class Loader(Protocol):
    """A loader module (`eea_co2`, `eea_obfcm`, `rdw`)."""

    async def fetch_rows(self, cfg: Any, make: str | None = None, *, makes: Iterable[str] | None = None,
                         transport: httpx.AsyncBaseTransport | None = None) -> list[DatasetRow]:  # fmt: skip
        """The dataset's rows of these makes."""
        ...

    def version(self, cfg: Any) -> str:
        """The dataset's version (part of its id)."""
        ...


class ApiDataset:
    """`DatasetReader` over a loader module; `transport` reaches the loader's HTTP client (tests)."""

    def __init__(self, loader: Loader, cfg: dict[str, Any], transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._loader = loader
        self._cfg = cfg
        self._transport = transport

    def info(self) -> DatasetInfo:
        """The load as `gold_datasets` records it (id with the version, next refresh from now)."""
        return meta(self._cfg, self._loader.version(self._cfg))

    async def rows(self, makes: list[str]) -> list[DatasetRow]:
        """The dataset's groups of these makes."""
        return await self._loader.fetch_rows(self._cfg, makes=makes, transport=self._transport)
