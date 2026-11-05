"""Gold matching: open-dataset rows -> gold values of one catalogue variant (spec 011 research R3). Pure.

Loaders (`gold/loaders/*`, `fetch_rows`) turn a dataset into `DatasetRow`s: one group of vehicles with its count,
values as published keyed by our attribute names, a declared conversion per attribute (`curb_mass` arrives as the EU
mass in running order with `eu_running_order_minus_driver`). `match()` keeps the rows of the variant and groups them
by engine (power, displacement):

- make through `config/makes.yaml` aliases; model tokens in the commercial name (make prefix, spaces and marketing
  words ignored, so "TOYOTA LANDCRUISER (150 SERIE" holds "land cruiser"); fuel (`hybrid` covers HEV and MHEV, as in
  the EEA data); registration years overlapping the generation's years; displacement within 2 % when known;
- power within 1 kW only for combustion variants: for hybrids and plug-ins the datasets give the ENGINE power and
  for BEVs an unreliable rating, while the catalogue holds the system power;
- `exact` (HIGH): a combustion variant with a power and one group left (mass in running order breaks a tie);
  `by_power` (MEDIUM): otherwise, one group left; several groups: an attribute gets gold only when every group agrees
  within its tolerance (the dataset cannot tell the variants apart, constitution II);
- groups of a single vehicle are noise and dropped.

A group's value is the registration-weighted median. `flag()` marks gold contradicted by two independent families
that agree with each other (spec edge case "gold disagrees with all sources").
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

MASS_CONVERSION = "eu_running_order_minus_driver"
ICE_FUELS = frozenset({"petrol", "diesel", "lpg", "cng", "e85"})
FUEL_SYNONYMS = {"gasoline": "petrol", "benzine": "petrol", "electric": "bev", "hev": "hybrid", "mhev": "hybrid",
                 "plug-in": "phev"}  # fmt: skip

Tolerance = tuple[str, float]  # ("abs" | "rel", value)


@dataclass(frozen=True)
class DatasetRow:
    """One group of an open dataset: the vehicles of one make / commercial name / fuel / power (/ mass / values) with
    their count. The matcher keys on make, model, fuel, power_kw, displacement_cc, years and mass (tie-break) and
    takes the registration-weighted median of `values` over the rows of one group (research R3).
    The loaders' interface (branch 011-us1-gold): keep these field names."""

    dataset: str  # loader kind: eea_co2 | eea_obfcm | rdw
    make: str  # as published (EEA "Mk", RDW "merk"); normalised by the matcher through config/makes.yaml
    model: str  # commercial name as published (EEA "Cn", RDW "handelsbenaming")
    fuel: str  # petrol | diesel | lpg | cng | e85 | hybrid | phev | bev | fcev | other ("hybrid" = HEV or MHEV)
    power_kw: float | None  # matching key: combustion-engine kW (also for hybrids and plug-ins), motor kW for a BEV
    displacement_cc: int | None
    mass_running_order_kg: float | None  # as published (EU running order: includes 75 kg driver); tie-break only
    year_from: int | None  # registration years the row covers
    year_to: int | None
    registrations: int  # weight (vehicles in the group)
    values: Mapping[str, float]  # gold attribute → value as published, unit in `units`
    units: Mapping[str, str]
    record_key: str  # dataset group key, stored as gold_values.record_key
    conversions: Mapping[str, str] = field(default_factory=dict)  # attribute → conversion rule (gold_datasets.yaml)
    details: Mapping[str, Any] = field(default_factory=dict)  # not compared: fuel mode, type approval, PHEV shares…


@dataclass(frozen=True)
class VariantKey:
    variant_id: str
    make: str
    model: str
    model_tokens: tuple[str, ...]
    fuel: str | None  # our vocabulary (vehicle_variants.fuel): petrol, diesel, hybrid, mhev, phev, bev, lpg
    power_kw: float | None  # catalogue power (the system power for hybrids)
    years: tuple[int | None, int | None] = (None, None)
    mass: float | None = None  # curb mass (kg) when known: tie-break only
    displacement_cc: int | None = None


@dataclass(frozen=True)
class GoldValue:
    variant_id: str
    attribute: str
    value_num: float | None
    unit: str
    tolerance: float
    tolerance_kind: str
    origin: str
    match_rule: str
    confidence: str
    dataset_id: str | None = None
    record_key: str | None = None
    registrations: int | None = None
    value_text: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MatchCfg:
    aliases: dict[str, list[str]] = field(default_factory=dict)  # canonical make -> aliases (config/makes.yaml)
    strip_words: tuple[str, ...] = ()
    tolerances: dict[str, Tolerance] = field(default_factory=dict)
    conversions: dict[str, float] = field(default_factory=lambda: {MASS_CONVERSION: -75.0})
    power_kw_tolerance: float = 1.0
    displacement_rel: float = 0.02
    mass_tiebreak_rel: float = 0.03
    min_registrations: int = 2
    default_tolerance: Tolerance = ("rel", 0.03)

    @classmethod
    def from_config(cls, gold: Mapping[str, Any], makes: Mapping[str, Any] | None = None) -> MatchCfg:
        """From `config/gold_datasets.yaml` and `config/makes.yaml`."""
        aliases = {
            str(k): [str(a) for a in (v or {}).get("aliases") or []]
            for k, v in ((makes or {}).get("makes") or {}).items()
        }
        tols: dict[str, Tolerance] = {}
        for attr, t in (gold.get("tolerances") or {}).items():
            kind = "abs" if "abs" in t else "rel"
            tols[str(attr)] = (kind, float(t[kind]))
        return cls(
            aliases=aliases,
            strip_words=tuple(str(w).lower() for w in gold.get("strip_words") or ()),
            tolerances=tols,
            conversions={str(k): float(v) for k, v in (gold.get("conversions") or {MASS_CONVERSION: -75}).items()},
        )

    def tolerance(self, attribute: str) -> Tolerance:
        return self.tolerances.get(attribute, self.default_tolerance)


# --- normalisation -----------------------------------------------------------------------------------------------


def norm_text(s: str) -> str:
    """Lower case, accents and punctuation stripped, spaces collapsed."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


def tokens(name: str, strip_words: tuple[str, ...] = ()) -> tuple[str, ...]:
    return tuple(t for t in norm_text(name).split() if t not in strip_words)


def canonical_make(make: str, aliases: dict[str, list[str]]) -> str:
    n = norm_text(make)
    for canon, names in aliases.items():
        if n == norm_text(canon) or n in {norm_text(a) for a in names}:
            return norm_text(canon)
    return n


def norm_fuel(fuel: str | None) -> str | None:
    if fuel is None:
        return None
    f = fuel.strip().lower()
    return FUEL_SYNONYMS.get(f, f)


def within(value: float, reference: float, tol: Tolerance) -> bool:
    kind, t = tol
    return abs(value - reference) <= (t if kind == "abs" else t * abs(reference)) + 1e-9


def weighted_median(pairs: list[tuple[float, int]]) -> float:
    """Median of values weighted by registrations (each weight at least 1; the lower median on a tie)."""
    items = sorted((v, max(1, int(w))) for v, w in pairs)
    half = sum(w for _, w in items) / 2
    acc = 0
    for v, w in items:
        acc += w
        if acc >= half:
            return v
    return items[-1][0]


# --- matching ----------------------------------------------------------------------------------------------------


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


def power_key(v: VariantKey) -> bool:
    """Whether the variant's power can be compared with a dataset's power (combustion engines only)."""
    return v.power_kw is not None and norm_fuel(v.fuel) in ICE_FUELS


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


def _group_key(row: DatasetRow) -> tuple[int | None, int | None]:
    return (round(row.power_kw) if row.power_kw else None), (
        round(row.displacement_cc / 50) if row.displacement_cc else None
    )


def _converted(attr: str, value: float, rule: str | None, cfg: MatchCfg) -> float:
    return value + cfg.conversions.get(rule, 0.0) if rule else value


@dataclass(frozen=True)
class _Agg:
    value: float
    registrations: int
    unit: str
    conversion: str | None


def _group_values(rows: list[DatasetRow], cfg: MatchCfg) -> dict[str, _Agg]:
    """attribute -> weighted median (after the declared conversion) of one group."""
    per: dict[str, list[tuple[float, int]]] = defaultdict(list)
    meta: dict[str, tuple[str, str | None]] = {}
    for r in rows:
        for attr, x in r.values.items():
            if x is None:
                continue
            rule = r.conversions.get(attr)
            per[attr].append((_converted(attr, float(x), rule, cfg), r.registrations))
            meta.setdefault(attr, (str(r.units.get(attr, "")), rule))
    regs = sum(r.registrations for r in rows)
    return {a: _Agg(weighted_median(p), regs, meta[a][0], meta[a][1]) for a, p in per.items()}


def _tie_break(groups: dict[Any, list[DatasetRow]], v: VariantKey, cfg: MatchCfg) -> dict[Any, list[DatasetRow]]:
    if v.mass is None or len(groups) < 2:
        return groups
    conv = cfg.conversions.get(MASS_CONVERSION, -75.0)
    tol = ("rel", cfg.mass_tiebreak_rel)
    kept = {
        k: rows
        for k, rows in groups.items()
        if any(
            r.mass_running_order_kg is not None and within(r.mass_running_order_kg + conv, v.mass, tol) for r in rows
        )
    }
    return kept or groups


def _chosen(groups: dict[Any, list[DatasetRow]], cfg: MatchCfg) -> tuple[dict[str, _Agg], bool]:
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


def match(rows: list[DatasetRow], variant: VariantKey, cfg: MatchCfg, dataset_id: str | None = None) -> list[GoldValue]:
    """Gold values of one variant from one dataset's rows (`dataset_id` defaults to the rows' dataset kind)."""
    kept = [r for r in rows if _keeps(r, variant, cfg)]
    if not kept:
        return []
    groups: dict[Any, list[DatasetRow]] = defaultdict(list)
    for r in kept:
        groups[_group_key(r)].append(r)
    groups = _tie_break(groups, variant, cfg)
    chosen, single = _chosen(groups, cfg)
    exact = single and power_key(variant)
    rule, confidence = ("exact", "HIGH") if exact else ("by_power", "MEDIUM")
    all_rows = [r for g in groups.values() for r in g]
    record_key = " ; ".join(sorted({r.record_key for r in all_rows}))[:1000]
    details: dict[str, Any] = {}
    for r in all_rows:
        for k, x in r.details.items():
            details.setdefault(k, x)
    out = []
    for attr, agg in sorted(chosen.items()):
        kind, tol = cfg.tolerance(attr)
        out.append(
            GoldValue(
                variant_id=variant.variant_id, attribute=attr, value_num=agg.value, unit=agg.unit, tolerance=tol,
                tolerance_kind=kind, origin="dataset",
                match_rule=f"{rule}+{agg.conversion}" if agg.conversion else rule, confidence=confidence,
                dataset_id=dataset_id or kept[0].dataset, record_key=record_key, registrations=agg.registrations,
                details=details,
            )
        )  # fmt: skip
    return out


def flag(gold: GoldValue, family_values: dict[str, float], tol: Tolerance) -> tuple[bool, str | None]:
    """Flag gold that ≥ 2 independent families contradict while agreeing with each other (within `tol`)."""
    if gold.value_num is None:
        return False, None
    against = sorted((v, f) for f, v in family_values.items() if not within(v, gold.value_num, tol))
    for a, _ in against:
        agreeing = [f for b, f in against if within(b, a, tol)]
        if len(agreeing) >= 2:
            fams = ", ".join(sorted(agreeing))
            return True, (
                f"{len(agreeing)} independent families ({fams}) agree on about {a:g} {gold.unit}; "
                f"gold {gold.value_num:g} {gold.unit} ({gold.match_rule})"
            )
    return False, None
