"""Gold matching: open-dataset rows -> gold values of one catalogue variant (spec 011 research R3). Pure.

Loaders turn a dataset into `DatasetRow`s: one group of vehicles with its count, values as published keyed by our
attribute names, a declared conversion per attribute (`curb_mass` arrives as the EU mass in running order with
`eu_running_order_minus_driver`). `match()` keeps the rows of the variant and groups them by engine (power,
displacement):

- make through `config/makes.yaml` aliases; model tokens in the commercial name (make prefix, spaces and marketing
  words ignored, so "TOYOTA LANDCRUISER (150 SERIE" holds "land cruiser"); fuel (`hybrid` covers HEV and MHEV, as in
  the EEA data); registration years overlapping the generation's years; displacement within 2 % when known;
- power within 1 kW only for combustion variants: for hybrids and plug-ins the datasets give the ENGINE power and
  for BEVs an unreliable rating, while the catalogue holds the system power;
- `exact` (HIGH): a combustion variant with a power and one group left (mass in running order breaks a tie);
  `by_power` (MEDIUM): otherwise, one group left; several groups: an attribute gets gold only when every group agrees
  within its tolerance (the dataset cannot tell the variants apart, constitution II);
- groups of a single vehicle are noise and dropped.

A group's value is the registration-weighted median.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from automind.acquisition.gold.domain.config import MASS_CONVERSION, MatchCfg
from automind.acquisition.gold.domain.records import CandidateVariant, DatasetRow, GoldValue, VariantKey
from automind.acquisition.gold.domain.text import (
    ICE_FUELS,
    canonical_make,
    norm_fuel,
    norm_text,
    tokens,
    weighted_median,
    within,
)
from automind.acquisition.parsing.normalise.fuel import fuel_of
from automind.shared.contracts.json import JsonObject

GroupKey = tuple[int | None, int | None]  # (engine kW, displacement in 50 cm3 steps)
_FUEL_BY_POWERTRAIN = {"BEV": "bev", "PHEV": "phev", "HEV": "hybrid", "MHEV": "mhev"}


def variant_key(v: CandidateVariant, cfg: MatchCfg) -> VariantKey:
    """What the matcher compares of a catalogue variant (its fuel from the powertrain or the name when unset)."""
    return VariantKey(
        variant_id=v.id, make=v.make, model=v.model, model_tokens=tokens(v.model, cfg.strip_words),
        fuel=_fuel_of_variant(v), power_kw=float(v.power_kw) if v.power_kw else None,
        years=(v.years_from, v.years_to), displacement_cc=v.engine_cc,
    )  # fmt: skip


def match(rows: list[DatasetRow], variant: VariantKey, cfg: MatchCfg, dataset_id: str | None = None) -> list[GoldValue]:
    """Gold values of one variant from one dataset's rows (`dataset_id` defaults to the rows' dataset kind)."""
    kept = [r for r in rows if _keeps(r, variant, cfg)]
    if not kept:
        return []
    groups: dict[GroupKey, list[DatasetRow]] = defaultdict(list)
    for r in kept:
        groups[_group_key(r)].append(r)
    groups = _tie_break(groups, variant, cfg)
    chosen, single = _chosen(groups, cfg)
    rule, confidence = ("exact", "HIGH") if single and power_key(variant) else ("by_power", "MEDIUM")
    all_rows = [r for g in groups.values() for r in g]
    record_key = " ; ".join(sorted({r.record_key for r in all_rows}))[:1000]
    details: JsonObject = {}
    for r in all_rows:
        for k, x in r.details.items():
            details.setdefault(k, x)
    return [
        GoldValue(
            variant_id=variant.variant_id, attribute=attr, value_num=agg.value, unit=agg.unit,
            tolerance=cfg.tolerance(attr)[1], tolerance_kind=cfg.tolerance(attr)[0], origin="dataset",
            match_rule=f"{rule}+{agg.conversion}" if agg.conversion else rule, confidence=confidence,
            dataset_id=dataset_id or kept[0].dataset, record_key=record_key, registrations=agg.registrations,
            details=details,
        )
        for attr, agg in sorted(chosen.items())
    ]  # fmt: skip


def power_key(v: VariantKey) -> bool:
    """Whether the variant's power can be compared with a dataset's power (combustion engines only)."""
    return v.power_kw is not None and norm_fuel(v.fuel) in ICE_FUELS


@dataclass(frozen=True)
class _Agg:
    value: float
    registrations: int
    unit: str
    conversion: str | None


def _fuel_of_variant(v: CandidateVariant) -> str | None:
    if v.fuel:
        return str(v.fuel).lower()
    pt = (v.powertrain or "").upper()
    if pt in _FUEL_BY_POWERTRAIN:
        return _FUEL_BY_POWERTRAIN[pt]
    return fuel_of(v.variant_name, v.powertrain)


def _model_ok(row: DatasetRow, v: VariantKey, cfg: MatchCfg) -> bool:
    make_words = set(norm_text(row.make).split()) | set(norm_text(v.make).split())
    have = tuple(t for t in tokens(row.model, cfg.strip_words) if t not in make_words)
    want = tuple(t for t in (v.model_tokens or tokens(v.model, cfg.strip_words)) if t not in cfg.strip_words)
    if not want:
        return False
    if all(t in have for t in want):
        return True
    # a multi-word name written as one word ("LANDCRUISER" holds "land cruiser"); never for one short token ("5")
    return len(want) > 1 and "".join(want) in have


def _years_ok(row: DatasetRow, v: VariantKey) -> bool:
    lo, hi = v.years
    r_lo, r_hi = row.year_from or row.year_to, row.year_to or row.year_from
    if r_lo is None or r_hi is None:
        return True
    return not ((hi is not None and r_lo > hi) or (lo is not None and r_hi < lo))


def _keeps(row: DatasetRow, v: VariantKey, cfg: MatchCfg) -> bool:
    if row.registrations < cfg.min_registrations:
        return False
    if canonical_make(row.make, cfg.aliases) != canonical_make(v.make, cfg.aliases) or not _model_ok(row, v, cfg):
        return False
    if v.fuel is not None and norm_fuel(row.fuel) != norm_fuel(v.fuel):
        return False
    if not _years_ok(row, v):
        return False
    cc_tol = ("rel", cfg.displacement_rel)
    if v.displacement_cc and row.displacement_cc and not within(row.displacement_cc, v.displacement_cc, cc_tol):
        return False
    if power_key(v):
        return row.power_kw is not None and abs(row.power_kw - float(v.power_kw or 0)) <= cfg.power_kw_tolerance
    return True


def _group_key(row: DatasetRow) -> GroupKey:
    kw = round(row.power_kw) if row.power_kw else None
    return kw, (round(row.displacement_cc / 50) if row.displacement_cc else None)


def _group_values(rows: list[DatasetRow], cfg: MatchCfg) -> dict[str, _Agg]:
    """attribute -> weighted median (after the declared conversion) of one group."""
    per: dict[str, list[tuple[float, int]]] = defaultdict(list)
    meta: dict[str, tuple[str, str | None]] = {}
    for r in rows:
        for attr, x in r.values.items():
            if x is None:
                continue
            rule = r.conversions.get(attr)
            per[attr].append((float(x) + cfg.conversions.get(rule, 0.0) if rule else float(x), r.registrations))
            meta.setdefault(attr, (str(r.units.get(attr, "")), rule))
    regs = sum(r.registrations for r in rows)
    return {a: _Agg(weighted_median(p), regs, meta[a][0], meta[a][1]) for a, p in per.items()}


def _tie_break(groups: dict[GroupKey, list[DatasetRow]], v: VariantKey,
               cfg: MatchCfg) -> dict[GroupKey, list[DatasetRow]]:  # fmt: skip
    if v.mass is None or len(groups) < 2:
        return groups
    conv = cfg.conversions.get(MASS_CONVERSION, -75.0)
    tol = ("rel", cfg.mass_tiebreak_rel)
    kept = {
        k: rows for k, rows in groups.items()
        if any(r.mass_running_order_kg is not None and within(r.mass_running_order_kg + conv, v.mass, tol)
               for r in rows)
    }  # fmt: skip
    return kept or groups


def _chosen(groups: dict[GroupKey, list[DatasetRow]], cfg: MatchCfg) -> tuple[dict[str, _Agg], bool]:
    """(values, single group?) — with several groups only the attributes on which every group agrees."""
    per_group = [_group_values(g, cfg) for g in groups.values()]
    if len(per_group) == 1:
        return per_group[0], True
    pooled = _group_values([r for g in groups.values() for r in g], cfg)
    return {
        a: agg
        for a, agg in pooled.items()
        if all(a in g and within(g[a].value, agg.value, cfg.tolerance(a)) for g in per_group)
    }, False
