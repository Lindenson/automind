"""Criteria weights from the persona, the profile, the wishes and the user's own adjustments (spec 007 US2). Pure.

    final = normalise(cap(persona base + profile rules + wish points)) + manual adjustments, normalised to 100

Every contribution keeps its reason, so the card can say "+10 practicality — family". Manual weights are
adjustments on top of the automatic ones (FR-010): a later persona or profile change still moves the rest, and
"back to automatic" removes them. Only fields the user stated or that were inferred from their words count;
assumed defaults never move a weight.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .casefile import CRITERION_KEYS, CaseFile

_BAND = re.compile(r"^(<=|>=|<|>)\s*(\d+)$")
RULE_FIELDS = ("family", "driving_style", "usage", "climate", "annual_km", "ownership_years", "condition")


@dataclass(frozen=True)
class WeightLine:
    base: float
    contributions: tuple[tuple[str, float], ...]
    manual: float
    final: float


@dataclass(frozen=True)
class WeightBreakdown:
    lines: dict[str, WeightLine]
    capped: tuple[str, ...] = ()
    excluded: tuple[str, ...] = ()
    manual: bool = False

    @property
    def final(self) -> dict[str, float]:
        return {k: ln.final for k, ln in self.lines.items() if ln.final > 0}


@dataclass(frozen=True)
class ProfileRules:
    cap: float = 50.0
    rules: dict[str, dict[str, dict[str, float]]] = field(default_factory=dict)

    @classmethod
    def from_config(cls, d: Mapping[str, Any] | None) -> ProfileRules:
        d = d or {}
        rules: dict[str, dict[str, dict[str, float]]] = {}
        for f, by_value in (d.get("rules") or {}).items():
            if f not in RULE_FIELDS:
                raise ValueError(f"profile_rules.yaml: unknown field {f!r}")
            rules[f] = {}
            for value, pts in (by_value or {}).items():
                if f in ("annual_km", "ownership_years") and not _BAND.match(str(value)):
                    raise ValueError(f"profile_rules.yaml: bad band {value!r} for {f}")
                bad = [k for k in pts if k not in CRITERION_KEYS]
                if bad:
                    raise ValueError(f"profile_rules.yaml: unknown criteria {bad} in {f}.{value}")
                rules[f][str(value)] = {k: float(v) for k, v in pts.items()}
        return cls(float(d["cap"]), rules)


def _in_band(band: str, x: float) -> bool:
    m = _BAND.match(band)
    if not m:
        return False
    op, n = m.group(1), float(m.group(2))
    return {"<": x < n, "<=": x <= n, ">": x > n, ">=": x >= n}[op]


def _counts(case: CaseFile, key: str) -> bool:
    return case.basis.get(key, "ASSUMED") != "ASSUMED"


def matched_rules(case: CaseFile, rules: ProfileRules) -> list[tuple[str, dict[str, float]]]:
    """(reason code, points) for every rule the case matches, in config order."""
    r = rules.rules
    return [*_person_rules(case, r), *_usage_rules(case, r), *_number_rules(case, r)]


def _person_rules(
    case: CaseFile, r: Mapping[str, Mapping[str, dict[str, float]]]
) -> list[tuple[str, dict[str, float]]]:
    out = []
    p = case.profile
    for f in ("family", "driving_style"):
        v = getattr(p, f)
        if v is not None and _counts(case, f) and v in r.get(f, {}):
            out.append((f"{f}.{v}", r[f][v]))
    if p.climate and p.climate in r.get("climate", {}) and (p.region or _counts(case, "region")):
        out.append((f"climate.{p.climate}", r["climate"][p.climate]))
    used = case.budget.intent == "USED" or (case.cars and all(c.condition == "USED" for c in case.cars))
    if used and "USED" in r.get("condition", {}):
        out.append(("condition.USED", r["condition"]["USED"]))
    return out


def _usage_rules(case: CaseFile, r: Mapping[str, Mapping[str, dict[str, float]]]) -> list[tuple[str, dict[str, float]]]:
    if not _counts(case, "usage"):
        return []
    skip = {"FAMILY"} if case.profile.family == "FAMILY" else set()  # the family rule already counts it
    return [
        (f"usage.{u}", r["usage"][u]) for u in dict.fromkeys(case.usage) if u not in skip and u in r.get("usage", {})
    ]


def _number_rules(
    case: CaseFile, r: Mapping[str, Mapping[str, dict[str, float]]]
) -> list[tuple[str, dict[str, float]]]:
    out: list[tuple[str, dict[str, float]]] = []
    if _counts(case, "annual_km"):
        out += [(f"annual_km.{b}", pts) for b, pts in r.get("annual_km", {}).items() if _in_band(b, case.annual_km)]
    if case.ownership_years and _counts(case, "ownership_years"):
        out += [(f"ownership_years.{b}", pts) for b, pts in r.get("ownership_years", {}).items()
                if _in_band(b, case.ownership_years)]  # fmt: skip
    return out


def _normalise(raw: Mapping[str, float], cap: float) -> tuple[dict[str, float], list[str]]:
    vals = {k: max(0.0, v) for k, v in raw.items() if v > 0}
    capped: list[str] = []
    for _ in range(len(vals) + 1):
        free = {k: v for k, v in vals.items() if k not in capped}
        room = 100.0 - cap * len(capped)
        total = sum(free.values())
        if total <= 0:
            break
        scaled = {k: v * room / total for k, v in free.items()}
        over = [k for k, v in scaled.items() if v > cap + 1e-9]
        if not over or cap >= 100:
            return {**{k: cap for k in capped}, **scaled}, capped
        capped += over
    return {k: cap for k in capped}, capped


Contributions = dict[str, list[tuple[str, float]]]


def automatic(case: CaseFile, personas: Mapping[str, Mapping[str, float]], strength_points: Mapping[str, float],
              rules: ProfileRules | None) -> tuple[dict[str, float], Contributions, list[str]]:  # fmt: skip
    """Persona base + rules + wishes, normalised and capped: (weights, contributions, capped)."""
    rules = rules or ProfileRules()
    raw = {k: float(v) for k, v in (personas.get(case.persona) or personas["UNKNOWN"]).items()}
    contrib: Contributions = {}
    for code, pts in matched_rules(case, rules):
        for k, v in pts.items():
            raw[k] = raw.get(k, 0.0) + v
            contrib.setdefault(k, []).append((code, v))
    for p in case.priorities:
        v = float(strength_points[p.strength])
        raw[p.criterion] = raw.get(p.criterion, 0.0) + v
        contrib.setdefault(p.criterion, []).append((f"priority.{p.strength}", v))
    w, capped = _normalise(raw, rules.cap)
    return w, contrib, capped


def _legacy_adjustments(case: CaseFile, auto: Mapping[str, float]) -> dict[str, float]:
    """A case from before spec 007 kept absolute weights; they become adjustments with the same result."""
    if case.weights_overridden and case.weights and not case.weight_adjustments:
        keys = set(auto) | set(case.weights)
        return {k: float(case.weights.get(k, 0.0)) - float(auto.get(k, 0.0)) for k in keys}
    return dict(case.weight_adjustments)


def breakdown(case: CaseFile, personas: Mapping[str, Mapping[str, float]], strength_points: Mapping[str, float],
              rules: ProfileRules | None) -> WeightBreakdown:  # fmt: skip
    base_raw = personas.get(case.persona) or personas["UNKNOWN"]
    base, _ = _normalise({k: float(v) for k, v in base_raw.items()}, 100.0)
    auto, contrib, capped = automatic(case, personas, strength_points, rules)
    adj = _legacy_adjustments(case, auto)
    excluded = [k for k in case.weights_excluded if k in CRITERION_KEYS]
    raw = {k: auto.get(k, 0.0) + adj.get(k, 0.0) for k in set(auto) | set(adj)}
    for k in excluded:
        raw[k] = 0.0
    final, _ = _normalise(raw, 100.0) if adj or excluded else (auto, [])
    keys = sorted(set(auto) | set(final) | set(adj) | set(excluded), key=lambda k: -final.get(k, 0.0))
    lines = {
        k: WeightLine(round(base.get(k, 0.0), 1), tuple(contrib.get(k, ())), round(adj.get(k, 0.0), 1),
                      round(final.get(k, 0.0), 4))
        for k in keys
    }  # fmt: skip
    manual = bool([v for v in adj.values() if abs(v) > 1e-6] or excluded)
    return WeightBreakdown(lines, tuple(capped), tuple(excluded), manual)


def manual_adjustments(case: CaseFile, wanted: Mapping[str, float], auto: Mapping[str, float]) -> dict[str, float]:
    """The user set absolute weights in the panel: store them as differences from the automatic weights."""
    total = sum(v for v in wanted.values() if v > 0)
    if total <= 0:
        raise ValueError("at least one weight must be > 0")
    target = {k: v * 100 / total for k, v in wanted.items() if v > 0}
    keys = set(auto) | set(target)
    return {k: round(target.get(k, 0.0) - auto.get(k, 0.0), 4) for k in keys
            if abs(target.get(k, 0.0) - auto.get(k, 0.0)) > 1e-6}  # fmt: skip
