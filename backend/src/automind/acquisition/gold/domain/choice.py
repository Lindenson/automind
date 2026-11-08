"""Which gold counts: the best stored value of each attribute, gold that independent families contradict, and the
gold a settled user challenge becomes."""

from __future__ import annotations

from collections.abc import Iterable

from automind.acquisition.gold.domain.config import GoldRules
from automind.acquisition.gold.domain.records import GoldValue, StoredGold
from automind.acquisition.gold.domain.text import Tolerance, within

CHALLENGES = "challenges"  # gold_datasets.id of user challenges
REFERENCE_SET = "reference_set"  # gold_datasets.id of the hand-checked reference set
_SETTLED = ("CONFIRMED", "CORRECTED")
_CONFIDENCE_RANK = {"HIGH": 0, "MEDIUM": 1}
_ORIGIN_RANK = {"reference_set": 0, "dataset": 1, "challenge": 2}


def best_by_attribute(rows: Iterable[StoredGold]) -> dict[str, StoredGold]:
    """One gold value per attribute: HIGH before MEDIUM, then reference set, dataset, challenge; newest first."""
    best: dict[str, StoredGold] = {}
    for r in sorted(rows, key=lambda r: r.verified_at, reverse=True):
        cur = best.get(r.attribute)
        if cur is None or _rank(r) < _rank(cur):
            best[r.attribute] = r
    return best


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


def challenge_gold(variant_id: str, attribute: str, outcome: str, value: str | float | None, challenge_id: str | None,
                   unit: str | None, rules: GoldRules) -> GoldValue | None:  # fmt: skip
    """The gold a CONFIRMED or CORRECTED user challenge becomes (origin `challenge`, MEDIUM until a dataset agrees);
    None for any other outcome or an empty value."""
    if outcome not in _SETTLED or value is None or str(value).strip() == "":
        return None
    num: float | None
    try:
        num, text = float(str(value).replace(",", ".")), None
    except ValueError:
        num, text = None, str(value)
    kind, tol = rules.tolerance_of(attribute)
    return GoldValue(
        variant_id=variant_id, attribute=attribute, value_num=num, value_text=text,
        unit=unit or rules.unit_of(attribute), tolerance=tol, tolerance_kind=kind, origin="challenge",
        match_rule=f"challenge_{outcome.lower()}", confidence="MEDIUM", dataset_id=CHALLENGES,
        record_key=challenge_id,
    )  # fmt: skip


def _rank(g: StoredGold) -> tuple[int, int]:
    return _CONFIDENCE_RANK.get(g.confidence, 9), _ORIGIN_RANK.get(g.origin, 9)
