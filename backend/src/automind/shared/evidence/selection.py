"""Selecting one value from several claims: agreement of independent sources, majority over a single higher authority,
confidence (research R5), and whether a claim may be about a sibling generation."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from automind.shared.evidence.sense import gearbox_conflict
from automind.shared.evidence.sources import AUTHORITY, assign_provenance
from automind.shared.vehicle.specs import ATTRS


@dataclass
class ClaimIn:
    claim_id: str
    attribute: str
    value: float | str
    source_type: str
    domain: str
    scope: str = "VARIANT"  # VARIANT | GENERATION | ENGINE


@dataclass
class Selected:
    attribute: str
    available: bool
    value: float | str | None = None
    provenance: str | None = None
    confidence: str | None = None
    confidence_rule: str | None = None
    claim_ids: list[str] = field(default_factory=list)
    conflict: bool = False
    resolution_rule: str | None = None
    alternatives: list[float | str] = field(default_factory=list)


_FUELS = {
    "diesel": ("diesel", "dci", "tdi", "crdi", "hdi", "bluehdi", "d-4d", "gasóleo", "gasoleo", "дизель"),
    "petrol": ("petrol", "gasoline", "gasolina", "benzin", "tsi", "tfsi", "бензин"),
    "electric": ("electric", "eléctrico", "electrico", "bev", "электро"),
}


_DRIVES = {
    "awd": "AWD",
    "4wd": "AWD",
    "4x4": "AWD",
    "all-wheel": "AWD",
    "all wheel": "AWD",
    "quattro": "AWD",
    "xdrive": "AWD",
    "4motion": "AWD",
    "fwd": "FWD",
    "front": "FWD",
    "delantera": "FWD",
    "rwd": "RWD",
    "rear": "RWD",
    "trasera": "RWD",
}


def _fuel(text: str) -> str | None:
    t = f" {text.lower()} "
    found = {f for f, words in _FUELS.items() if any(w in t for w in words)}
    return next(iter(found)) if len(found) == 1 else None


def _drive(text: str) -> str | None:
    t = text.lower()
    found = {d for w, d in _DRIVES.items() if w in t}
    return next(iter(found)) if len(found) == 1 else None


def _agree_text(key: str, a: str, b: str) -> bool:
    """FR-032: gearbox, drive and fuel are compared normalised; other texts are not compared."""
    if key == "transmission":
        return not gearbox_conflict(a, b)
    if key == "drivetrain":
        da, db = _drive(a), _drive(b)
        return da == db if da and db else a.strip().lower() == b.strip().lower()
    if key == "engine":
        fa, fb = _fuel(a), _fuel(b)
        return not (fa and fb and fa != fb)
    return True


def _agree(attr_key: str, a: float | str, b: float | str) -> bool:
    attr = ATTRS[attr_key]
    if attr.kind == "text" or isinstance(a, str) or isinstance(b, str):
        return _agree_text(attr.key, str(a), str(b))
    if attr.tolerance == 0:
        return float(a) == float(b)
    ref = max(abs(float(a)), abs(float(b)), 1e-9)
    return abs(float(a) - float(b)) / ref <= attr.tolerance


def _clusters(attr_key: str, claims: list[ClaimIn]) -> list[list[ClaimIn]]:
    clusters: list[list[ClaimIn]] = []
    for c in claims:
        for cl in clusters:
            if _agree(attr_key, cl[0].value, c.value):
                cl.append(c)
                break
        else:
            clusters.append([c])
    return clusters


MAJORITY_OVER_AUTHORITY = 3  # independent domains that agree and outweigh a single higher-authority value


def _value_key(v: float | str) -> tuple[int, float, str]:
    """Values in a fixed order: numbers ascending (a tie keeps the base configuration: 5 seats before 7), then
    texts."""
    if isinstance(v, int | float):
        return (0, float(v), "")
    return (1, 0.0, str(v).strip().lower())


def _order(c: ClaimIn) -> tuple[Any, ...]:
    """The order claims are read in: authority, then the value, then the site; the claim id (random, new on every
    research run) only last (009 FR-024: two reports of one chat showed different seats and boot volume)."""
    return (AUTHORITY.index(c.source_type), _value_key(c.value), c.domain, c.claim_id)


def _value_of(cl: list[ClaimIn]) -> float | str:
    """The value a cluster stands for: the one most sites give, then most claims, then the first in value order."""
    by: dict[tuple[int, float, str], list[ClaimIn]] = defaultdict(list)
    for c in cl:
        by[_value_key(c.value)].append(c)
    best = min(by.items(), key=lambda kv: (-len({c.domain for c in kv[1]}), -len(kv[1]), kv[0]))
    return best[1][0].value


def _strength(cl: list[ClaimIn]) -> tuple[Any, ...]:
    """Clusters compared by the sites behind them, then their claims, then their value (never by read order)."""
    return (-len({c.domain for c in cl}), -len(cl), _value_key(_value_of(cl)))


def select_value(attr_key: str, claims: list[ClaimIn]) -> Selected:
    """FR-017 resolution + FR-018 confidence for one attribute of one variant."""
    if not claims:
        return Selected(attr_key, available=False)
    claims = sorted(claims, key=_order)
    all_clusters = _clusters(attr_key, claims)
    conflict = len(all_clusters) > 1
    top_rank = claims[0].source_type
    top = [c for c in claims if c.source_type == top_rank]
    top_clusters = sorted(_clusters(attr_key, top), key=_strength)
    rule: str | None = None
    crowd = min(all_clusters, key=_strength)
    crowd_n, top_n = len({c.domain for c in crowd}), len({c.domain for c in top_clusters[0]})
    if (
        crowd_n >= MAJORITY_OVER_AUTHORITY
        and crowd_n >= 2 * top_n
        and not _agree(attr_key, _value_of(crowd), _value_of(top_clusters[0]))
    ):
        # chat fcf5b3b8: kia.com's engine-only torque (265 Nm) beat three sources agreeing on 350 Nm. Several
        # independent sites that agree outweigh one page, whatever its authority.
        winner, rule, top_rank = crowd, "MAJORITY_OVER_SINGLE", crowd[0].source_type
    elif len(top_clusters) == 1:
        winner = top_clusters[0]
        rule = "AUTHORITY_ORDER" if conflict else None
    elif len({c.domain for c in top_clusters[0]}) >= 2 and len({c.domain for c in top_clusters[0]}) > len(
        {c.domain for c in top_clusters[1]}
    ):
        winner = top_clusters[0]
        rule = "MAJORITY_SAME_RANK"
    else:
        alts = [_value_of(cl) for cl in all_clusters]
        return Selected(
            attr_key,
            True,
            value=_value_of(top_clusters[0]),
            provenance=assign_provenance(top_rank, attr_key),
            confidence="LOW",
            confidence_rule="LOW:UNRESOLVED_CONFLICT",
            claim_ids=[c.claim_id for c in claims],
            conflict=True,
            alternatives=alts,
        )
    value = _value_of(winner)
    supporting = [c for c in claims if _agree(attr_key, c.value, value)]
    domains = {c.domain for c in supporting}
    if all(c.scope != "VARIANT" for c in winner):
        conf, crule = "LOW", "LOW:INDIRECT_SCOPE"
    elif top_rank == "MANUFACTURER" and rule != "MAJORITY_OVER_SINGLE":
        conf, crule = "HIGH", "HIGH:MANUFACTURER"
    elif len(domains) >= 2:
        conf, crule = "HIGH", "HIGH:2_INDEPENDENT_AGREE"
    else:
        conf, crule = "MEDIUM", "MEDIUM:SINGLE_SOURCE"
    alts = [_value_of(cl) for cl in all_clusters if not _agree(attr_key, _value_of(cl), value)]
    return Selected(
        attr_key,
        True,
        value=value,
        provenance=assign_provenance(top_rank, attr_key),
        confidence=conf,
        confidence_rule=crule,
        claim_ids=[c.claim_id for c in supporting],
        conflict=conflict,
        resolution_rule=rule,
        alternatives=alts,
    )


def select_all(claims: list[ClaimIn]) -> dict[str, Selected]:
    by_attr: dict[str, list[ClaimIn]] = defaultdict(list)
    for c in claims:
        by_attr[c.attribute].append(c)
    return {k: select_value(k, by_attr.get(k, [])) for k in ATTRS}


def _mentions(code: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(code.lower())}(?![A-Za-z0-9])", text) is not None


_CODE_RE = re.compile(r"^([a-z]+)\s?(\d+(?:\.\d)?)$")


def sibling_code(generation: str, low: str) -> bool:
    """Another code of the same family on the page ("mk2" when the target is "Mk1", "j250" vs "J150")."""
    m = _CODE_RE.match(generation.strip().lower())
    if m is None:
        return False
    prefix, number = m.groups()
    found = re.findall(rf"(?<![a-z0-9]){prefix}\s?(\d+(?:\.\d)?)(?![a-z0-9])", low)
    width = len(number.split(".")[0])
    return any(n != number and len(n.split(".")[0]) == width for n in found)


def variant_match_uncertain(
    text: str,
    title: str,
    generation: str | None,
    other_generations: list[str],
    years: tuple[int | None, int | None] = (None, None),
) -> bool:
    """True when a page may not be about the target generation (→ validator role, constitution XI).

    Uncertain if the page names another generation of the same model, or names neither the target
    generation nor a year inside its production years.
    """
    low = f"{title}\n{text}".lower()
    if any(_mentions(g, low) for g in other_generations if g and g != generation):
        return True
    if generation and sibling_code(generation, low):
        return True
    if generation and _mentions(generation, low):
        return False
    lo, hi = years
    if lo is not None:
        top = hi if hi is not None else lo + 15
        if any(str(y) in low for y in range(lo, top + 1)):
            return False
    return True
