"""Distinct registered versions of a model from the open datasets (spec 011 identity readers). Pure.

The EEA CO2 tables (and RDW) list every registration group of a make / commercial name / fuel / engine kW / cm3 /
year. Grouped by engine (fuel, kW, cm3) over the years, they tell which engines a model was registered with and
when each first and last appeared: the Kia Sorento MQ4 PHEV shows a 132 kW engine 2021–2023 and a 118 kW engine
from 2024 (the facelift). For hybrids and plug-ins the kW is the COMBUSTION ENGINE's, never the system power (the
loaders' pitfalls): it is kept as `engine_kw` and `power_is_max` is false; only a combustion car's kW is its power.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from automind.acquisition.gold.domain.records import DatasetRow
from automind.acquisition.gold.domain.text import ICE_FUELS, canonical_make, norm_fuel, norm_text, tokens
from automind.shared.contracts.json import JsonObject

_FUELS = frozenset({"petrol", "diesel", "lpg", "cng", "e85", "hybrid", "phev", "bev", "fcev", "other"})


@dataclass(frozen=True)
class IdRow:
    """One dataset group reduced to what identifies a version (`registrations` 0: unknown, e.g. a stored key)."""

    dataset: str
    make: str
    model: str
    fuel: str
    engine_kw: float | None
    displacement_cc: int | None
    year_from: int | None
    year_to: int | None
    registrations: int = 0


@dataclass(frozen=True)
class RegisteredVersion:
    """One engine a model was registered with (fuel, kW, cm3) and the years it was registered in."""

    fuel: str
    engine_kw: int | None
    displacement_cc: int | None
    years_from: int | None
    years_to: int | None  # None: still registered in the newest year of the data
    registrations: int
    power_is_max: bool  # a combustion engine: its kW is the car's power
    datasets: tuple[str, ...]
    names: tuple[str, ...]  # commercial names as published


@dataclass(frozen=True)
class VersionLimits:
    """How the registered versions are asked for (config/search.yaml `intake`)."""

    timeout_s: float = 20.0  # the live dataset query
    min_registrations: int = 10  # a group below this is noise (single imports)

    @classmethod
    def from_intake(cls, intake: JsonObject) -> VersionLimits:
        """From the `intake` section (defaults for what it leaves out)."""
        return cls(float(intake.get("dataset_versions_timeout_s", cls.timeout_s)),
                   int(intake.get("dataset_versions_min_registrations", cls.min_registrations)))  # fmt: skip


def id_row(r: DatasetRow) -> IdRow:
    """A dataset row reduced to what identifies a version."""
    return IdRow(r.dataset, r.make, r.model, r.fuel, r.power_kw, r.displacement_cc, r.year_from, r.year_to,
                 r.registrations)  # fmt: skip


def rows_of_keys(keys: Iterable[str], dataset: str = "eea_co2") -> list[IdRow]:
    """EEA CO2 group keys as stored in gold_values.record_key ("KIA|SORENTO|phev|118|1598|2024", several joined by
    " ; "): one row each; other keys are skipped."""
    out: list[IdRow] = []
    for raw in keys:
        for key in (raw or "").split(" ; "):
            parts = key.strip().split("|")
            if len(parts) != 6:
                continue
            make, model, fuel, kw, cc, yr = parts
            year = _int(yr)
            if fuel not in _FUELS or year is None or not (1990 <= year <= 2100):
                continue
            out.append(IdRow(dataset, make, model, fuel, _int(kw), _int(cc), year, year))
    return out


def group(
    rows: Sequence[IdRow], make: str, model: str, *, fuel: str | None = None, year_from: int | None = None,
    aliases: dict[str, list[str]] | None = None, strip_words: tuple[str, ...] = (), min_registrations: int = 1,
) -> list[RegisteredVersion]:  # fmt: skip
    """The distinct versions (fuel, engine kW, cm3) of `make` `model` registered from `year_from`, newest first.
    A group whose registrations are known and below `min_registrations` is noise (single imports) and dropped."""
    want_make, want_fuel = canonical_make(make, aliases or {}), norm_fuel(fuel)
    kept = [
        r for r in rows
        if canonical_make(r.make, aliases or {}) == want_make and _model_ok(r, make, model, strip_words)
        and (want_fuel is None or norm_fuel(r.fuel) == want_fuel)
        and (year_from is None or (r.year_to or r.year_from or 0) >= year_from)
    ]  # fmt: skip
    if not kept:
        return []
    newest = max((r.year_to or r.year_from or 0) for r in kept)
    per: dict[tuple[str, int | None, int | None], list[IdRow]] = {}
    for r in kept:
        kw = round(r.engine_kw) if r.engine_kw else None
        cc = round(r.displacement_cc / 50) if r.displacement_cc else None
        per.setdefault((norm_fuel(r.fuel) or r.fuel, kw, cc), []).append(r)
    out: list[RegisteredVersion] = []
    for (f, kw, _), rs in per.items():
        regs = sum(r.registrations for r in rs)
        if regs and regs < min_registrations:
            continue
        ccs = sorted(r.displacement_cc for r in rs if r.displacement_cc)
        lo = min((y for r in rs if (y := r.year_from or r.year_to)), default=None)
        hi = max((y for r in rs if (y := r.year_to or r.year_from)), default=None)
        out.append(RegisteredVersion(
            fuel=f, engine_kw=kw, displacement_cc=ccs[len(ccs) // 2] if ccs else None, years_from=lo,
            years_to=None if hi is None or hi >= newest else hi, registrations=regs,
            power_is_max=f in ICE_FUELS and kw is not None,
            datasets=tuple(sorted({r.dataset for r in rs})), names=tuple(sorted({r.model for r in rs}))[:4],
        ))  # fmt: skip
    return sorted(out, key=lambda v: (v.years_to is not None, -(v.years_from or 0), v.fuel, v.engine_kw or 0))


def _int(x: str) -> int | None:
    try:
        return int(float(x))
    except ValueError:
        return None


def _model_ok(row: IdRow, make: str, model: str, strip: tuple[str, ...]) -> bool:
    make_words = set(norm_text(row.make).split()) | set(norm_text(make).split())
    have = tuple(t for t in tokens(row.model, strip) if t not in make_words)
    want = tuple(t for t in tokens(model, strip) if t not in make_words)
    if not want:
        return False
    return all(t in have for t in want) or (len(want) > 1 and "".join(want) in have)
