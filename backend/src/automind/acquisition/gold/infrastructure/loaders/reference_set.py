"""The hand-checked reference set `eval/reference_vehicles.yaml` (spec 011 T023): `ReferenceFile` is the services'
`ReferenceSet`. Entries without `sources` are left out (constitution I); the gold rule is `gold.domain.reference`."""

from __future__ import annotations

from pathlib import Path

import yaml

from automind.acquisition.gold.domain.choice import REFERENCE_SET
from automind.acquisition.gold.domain.records import DatasetInfo
from automind.shared.contracts.json import JsonObject
from automind.shared.infrastructure.config import loader as config

INFO = DatasetInfo(REFERENCE_SET, "Reference vehicles (hand-checked, sourced)", "reference_set", "internal",
                   url="eval/reference_vehicles.yaml", refresh_days=1)  # fmt: skip


class ReferenceFile:
    """`ReferenceSet` over the YAML file (`path`; the repository's `eval/reference_vehicles.yaml` when None)."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path

    def info(self) -> DatasetInfo:
        """The reference set as a load records it (refreshed daily)."""
        return INFO

    def entries(self) -> list[JsonObject]:
        """The entries that cite their sources."""
        path = self._path or config.config_dir().parent / "eval" / "reference_vehicles.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return [e for e in data.get("vehicles") or [] if isinstance(e, dict) and e.get("sources")]
