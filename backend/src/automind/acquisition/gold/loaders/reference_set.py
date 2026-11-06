"""Gold from the hand-checked reference set `eval/reference_vehicles.yaml` (spec 011 T023, research R3).

Each entry names its variant (make, model, generation, variant name) and cites its sources; entries without
`sources` are skipped (constitution I). Values become gold with origin `reference_set`, confidence HIGH.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from automind.acquisition.gold.domain.match import GoldValue, norm_text
from automind.acquisition.gold.repo import REFERENCE_SET, DatasetInfo, tolerance_of, unit_of
from automind.shared.infrastructure.config import loader as config
from automind.shared.vehicle import specs

INFO = DatasetInfo(REFERENCE_SET, "Reference vehicles (hand-checked, sourced)", "reference_set", "internal",
                   url="eval/reference_vehicles.yaml", refresh_days=1)  # fmt: skip


def path() -> Path:
    return config.config_dir().parent / "eval" / "reference_vehicles.yaml"


def read_entries(p: Path | None = None) -> list[dict[str, Any]]:
    data = yaml.safe_load((p or path()).read_text(encoding="utf-8")) or {}
    return [e for e in data.get("vehicles") or [] if isinstance(e, dict) and e.get("sources")]


def _key(make: str, model: str, generation: str | None, variant: str) -> tuple[str, str, str, str]:
    return norm_text(make), norm_text(model), norm_text(generation or ""), norm_text(variant)


def gold_values(entries: list[dict[str, Any]], variants: list[Any]) -> list[GoldValue]:
    """Gold for the variants (objects with id, make, model, generation, variant_name) that an entry names."""
    by_key: dict[tuple[str, str, str, str], list[str]] = {}
    for v in variants:
        by_key.setdefault(_key(v.make, v.model, v.generation, v.variant_name), []).append(v.id)
    out: list[GoldValue] = []
    for e in entries:
        k = _key(str(e.get("make", "")), str(e.get("model", "")), e.get("generation"), str(e.get("variant_name", "")))
        ids = by_key.get(k) or by_key.get((k[0], k[1], "", k[3])) or []
        values = dict(e.get("specs") or {})
        if e.get("measured_0_100") is not None:
            values["measured_0_100"] = e["measured_0_100"]
        for vid in ids:
            for attr, raw in values.items():
                if attr not in specs.ATTRS or raw is None:
                    continue
                kind, tol = tolerance_of(attr)
                num = float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else None
                out.append(
                    GoldValue(
                        variant_id=vid,
                        attribute=attr,
                        value_num=num,
                        value_text=None if num is not None else str(raw),
                        unit=unit_of(attr),
                        tolerance=tol,
                        tolerance_kind=kind,
                        origin="reference_set",
                        match_rule="reference_set",
                        confidence="HIGH",
                        dataset_id=REFERENCE_SET,
                        record_key=" ".join(k).strip(),
                    )  # fmt: skip
                )
    return out
