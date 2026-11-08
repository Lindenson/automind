"""The registered-versions reader wired over the database, the engine's live dataset port and
`config/gold_datasets.yaml` (EEA CO2) with `config/search.yaml intake`. Callers use these."""

from __future__ import annotations

from automind.acquisition.gold.domain.records import DatasetRow
from automind.acquisition.gold.domain.text import norm_text
from automind.acquisition.gold.infrastructure.loaders import eea_co2
from automind.acquisition.gold.infrastructure.wiring import dataset_cfg, match_cfg
from automind.acquisition.identity_readers.application.dataset_versions import DatasetVersions
from automind.acquisition.identity_readers.domain.registered import VersionLimits
from automind.acquisition.identity_readers.infrastructure.version_store import DATASET, VersionStore
from automind.acquisition.ports import AcqPorts


def dataset_versions(ports: AcqPorts) -> DatasetVersions:
    """The reader over the engine's ports (`ports.datasets`: the live query, None for stored and cached only)."""
    limits = VersionLimits.from_intake(dict((ports.ref.search or {}).get("intake") or {}))
    refresh_days = float(dataset_cfg(DATASET).get("refresh_days", 30))
    return DatasetVersions(VersionStore(), ports.datasets, limits, match_cfg(), refresh_days)


async def live_rows(make: str) -> list[DatasetRow]:
    """The live dataset query of one make (the engine port `AcqPorts.datasets` in production)."""
    return await eea_co2.fetch_rows(dataset_cfg(DATASET), make=norm_text(make).upper())


def source_url() -> str:
    """Where a person can see the dataset (its data hub page, else its API)."""
    cfg = dataset_cfg(DATASET)
    return str(cfg.get("datahub") or cfg.get("url") or "")
