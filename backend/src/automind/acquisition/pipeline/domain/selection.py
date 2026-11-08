"""The selected value of every attribute of a variant (spec 002 FR-017/FR-018): from all its accepted claims by the
evidence rules, a price far from the other sources' prices left out (spec 005), and the service interval taken from
the schedule when no source states it (European sources only). Also the votes that settle the variant's gearbox
(spec 004 FR-028) and the make's positioning (FR-028 status)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from automind.shared import evidence as ev
from automind.shared.evidence import sense

MONEY_ATTRS = ("official_price_es",)
INTERVALS = ("service_interval_km", "service_interval_months")


@dataclass(frozen=True)
class ScheduleItem:
    """An accepted service-schedule item and the URLs of its evidence ("" for evidence no longer stored)."""

    item: str
    interval_km: int | None
    interval_months: int | None
    urls: tuple[str, ...]


@dataclass(frozen=True)
class SelectedValue:
    """One `spec_values` row: the attribute's selected value, its confidence and the claims behind it."""

    attribute: str
    available: bool
    value_num: float | None
    value_text: str | None
    provenance: str | None
    confidence: str | None
    confidence_rule: str | None
    resolution_rule: str | None
    claim_ids: list[str]
    alternatives: list[float | str]


def select_values(claims: list[ev.ClaimIn], schedule: Sequence[ScheduleItem]) -> list[SelectedValue]:
    """Every attribute's value from the accepted claims; the schedule's interval replaces an empty one."""
    selected = ev.select_all(without_price_outliers(claims))
    derived = interval_from_schedule(schedule, selected)
    rows = [_row(key, sel) for key, sel in selected.items() if key not in derived]
    rows += [SelectedValue(attribute=key, available=True, value_num=float(value), value_text=None,
                           provenance="SOURCED_FACT", confidence="MEDIUM", confidence_rule="from the service schedule",
                           resolution_rule="schedule", claim_ids=[], alternatives=[])
             for key, value in derived.items()]  # fmt: skip
    return rows


def without_price_outliers(claims: list[ev.ClaimIn]) -> list[ev.ClaimIn]:
    """A price far from the other sources' prices of the same version is never selected (spec 005 fix)."""
    prices = [(i, float(c.value)) for i, c in enumerate(claims)
              if c.attribute in MONEY_ATTRS and isinstance(c.value, int | float)]  # fmt: skip
    bad = {prices[j][0] for j in sense.price_outliers([v for _, v in prices])}
    return [c for i, c in enumerate(claims) if i not in bad]


def interval_from_schedule(schedule: Sequence[ScheduleItem], selected: dict[str, ev.Selected]) -> dict[str, int]:
    """Service interval from the schedule items when no source states it as a single value (user report
    2026-11-02: the Tucson had a schedule but "no service interval"); items from other markets are not used."""
    want = [k for k in INTERVALS if k not in selected or not selected[k].available]
    if not want:
        return {}
    usable = [(m.item, m.interval_km, m.interval_months) for m in schedule
              if all(sense.market_fits(url, "maintenance").ok for url in m.urls)]  # fmt: skip
    km, months = sense.service_interval_from_items(usable)
    out = {"service_interval_km": km, "service_interval_months": months}
    return {k: v for k, v in out.items() if k in want and v}


def gearbox_families(transmissions: Sequence[str]) -> list[str]:
    """Gearbox families of transmission texts (unknown wording left out)."""
    return [f for f in (sense.gearbox_family(t) for t in transmissions) if f]


def mixed_families(families: list[str]) -> bool:
    """Two of the families contradict each other (manual vs automatic, DCT vs CVT, …)."""
    return any(sense.gearbox_conflict(a, b) for i, a in enumerate(families) for b in families[i + 1 :])


def unanimous_gearbox(families: list[str]) -> str | None:
    """The gearbox at least two claims agree on: one specific family, or "automatic" when none is more specific."""
    specific = [f for f in families if f != "automatic"]
    if len(families) < 2 or mixed_families(families):
        return None
    if not specific:
        return "automatic"
    return specific[0] if len(set(specific)) == 1 else None


def positioning_vote(positionings: Sequence[str]) -> str | None:
    """The make's most stated positioning (ties: the alphabetically first), None without any."""
    votes: dict[str, int] = defaultdict(int)
    for p in positionings:
        votes[str(p)] += 1
    return max(sorted(votes), key=lambda k: votes[k]) if votes else None


def _row(key: str, sel: ev.Selected) -> SelectedValue:
    return SelectedValue(attribute=key, available=sel.available,
                         value_num=sel.value if isinstance(sel.value, float) else None,
                         value_text=sel.value if isinstance(sel.value, str) else None, provenance=sel.provenance,
                         confidence=sel.confidence, confidence_rule=sel.confidence_rule,
                         resolution_rule=sel.resolution_rule, claim_ids=sel.claim_ids,
                         alternatives=sel.alternatives)  # fmt: skip
