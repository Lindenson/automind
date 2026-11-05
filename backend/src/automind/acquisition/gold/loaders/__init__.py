"""Spec 011 loaders of open datasets for gold values (research R3, config/gold_datasets.yaml).

Each loader module exposes `async def fetch_rows(cfg, make=None, *, makes=None, transport=None) -> list[DatasetRow]`
where `cfg` is the dataset's mapping under `datasets:` in config/gold_datasets.yaml and `transport` an optional
httpx transport (tests pass `httpx.MockTransport`). Requests go straight to the official open-data APIs with a
timeout — never through the web fetch policy (datasets are not web pages). A pinned column missing from a response
raises `SchemaChanged`: a new release is checked by a person and pinned again, never guessed.
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

USER_AGENT = "AutoMind gold loader (spec 011; open-data re-use with attribution)"

_MAKE = re.compile(r"^[A-Z0-9][A-Z0-9 .&'()/-]{0,40}$")


class SchemaChanged(RuntimeError):
    """A dataset response lacks a column pinned in config/gold_datasets.yaml."""


@dataclass(frozen=True)
class DatasetMeta:
    """What `gold_datasets` stores about a load (data-model 0019)."""

    id: str
    name: str
    kind: str
    version: str
    licence: str
    url: str
    next_refresh_at: datetime


def meta(cfg: Mapping[str, Any], version: str, now: datetime | None = None) -> DatasetMeta:
    now = now or datetime.now(UTC)
    kind = str(cfg["kind"])
    return DatasetMeta(
        id=f"{kind}_{version}" if version else kind,  # eea_co2_2024, eea_obfcm_2024, rdw
        name=str(cfg["name"]),
        kind=kind,
        version=version,
        licence=str(cfg["licence"]),
        url=str(cfg["url"]),
        next_refresh_at=now + timedelta(days=int(cfg["refresh_days"])),
    )


def wanted_makes(make: str | None, makes: Iterable[str] | None) -> list[str] | None:
    """Upper-case makes to ask for (None = every make). Values go into SQL/SoQL text, so only plain names pass."""
    out = sorted({m.strip().upper() for m in ([make] if make else []) + list(makes or []) if m and m.strip()})
    for m in out:
        if not _MAKE.match(m):
            raise ValueError(f"unexpected make name {m!r}")
    return out or None


def quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def require(found: Iterable[str], columns: Mapping[str, str], dataset: str, *, keys: Sequence[str] = ()) -> None:
    """Raise SchemaChanged when a pinned column (all of `columns`, or only `keys` of it) is absent."""
    have = set(found)
    missing = [columns[k] for k in (keys or list(columns)) if columns[k] not in have]
    if missing:
        raise SchemaChanged(f"{dataset}: columns {missing} missing (config/gold_datasets.yaml pins them)")


def num(value: Any) -> float | None:
    """A dataset number: None for empty, NULL, zero-length or non-numeric text."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip()
    if not text or text.upper() in ("NULL", "NAN", "NONE"):
        return None
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def pos(value: Any) -> float | None:
    """A positive dataset number (0 means "not reported" in these datasets)."""
    v = num(value)
    return v if v is not None and v > 0 else None


def fuel_of(fuel_type: str | None, fuel_mode: str | None) -> str:
    """EEA fuel type + fuel mode → our powertrain word (data-model: petrol, diesel, hybrid, phev, bev, …).
    Mode H covers full and mild hybrids alike: the EEA data cannot tell them apart."""
    ft = (fuel_type or "").strip().lower()
    fm = (fuel_mode or "").strip().upper()
    if ft == "electric":
        return "bev"
    if ft == "hydrogen":
        return "fcev"
    if fm == "P":
        return "phev"
    if fm == "H" or ft.endswith("/electric"):
        return "hybrid"
    return {"petrol": "petrol", "diesel": "diesel", "lpg": "lpg", "ng": "cng", "ng-biomethane": "cng"}.get(
        ft, "e85" if ft == "e85" else "other"
    )


def weighted_median(pairs: Iterable[tuple[float, float]]) -> float | None:
    """Median of values weighted by counts (lower median on a tie)."""
    items = sorted((v, w) for v, w in pairs if w > 0)
    if not items:
        return None
    half = sum(w for _, w in items) / 2
    acc = 0.0
    for v, w in items:
        acc += w
        if acc >= half:
            return v
    return statistics.median(v for v, _ in items)  # pragma: no cover - unreachable


def year_of(yyyymmdd: Any) -> int | None:
    text = str(yyyymmdd or "")
    return int(text[:4]) if len(text) >= 4 and text[:4].isdigit() else None
