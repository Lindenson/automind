"""Gold from the hand-checked reference set `eval/reference_vehicles.yaml` (spec 011 T023, research R3).

Each entry names its variant (make, model, generation, variant name) and cites its sources; entries without `sources`
are left out by the reader (constitution I). An entry without a generation, or one whose generation matches no
variant, names the variant of that make, model and name. Values become gold with origin `reference_set`, HIGH.
"""

from __future__ import annotations

from automind.acquisition.gold.domain.choice import REFERENCE_SET
from automind.acquisition.gold.domain.config import GoldRules
from automind.acquisition.gold.domain.records import CandidateVariant, GoldValue
from automind.acquisition.gold.domain.text import norm_text
from automind.shared.contracts.json import JsonObject
from automind.shared.vehicle import specs

_Key = tuple[str, str, str, str]


def reference_gold(entries: list[JsonObject], variants: list[CandidateVariant], rules: GoldRules) -> list[GoldValue]:
    """Gold for the variants an entry names: each known attribute of its `specs` (and `measured_0_100`)."""
    by_key: dict[_Key, list[str]] = {}
    for v in variants:
        by_key.setdefault(_key(v.make, v.model, v.generation, v.variant_name), []).append(v.id)
    out: list[GoldValue] = []
    for e in entries:
        k = _key(str(e.get("make", "")), str(e.get("model", "")), e.get("generation"), str(e.get("variant_name", "")))
        ids = by_key.get(k) or by_key.get((k[0], k[1], "", k[3])) or []
        values = dict(e.get("specs") or {})
        if e.get("measured_0_100") is not None:
            values["measured_0_100"] = e["measured_0_100"]
        out += [_gold(vid, attr, raw, " ".join(k).strip(), rules)
                for vid in ids for attr, raw in values.items() if attr in specs.ATTRS and raw is not None]  # fmt: skip
    return out


def _key(make: str, model: str, generation: str | None, variant: str) -> _Key:
    return norm_text(make), norm_text(model), norm_text(generation or ""), norm_text(variant)


def _gold(variant_id: str, attr: str, raw: object, record_key: str, rules: GoldRules) -> GoldValue:
    kind, tol = rules.tolerance_of(attr)
    num = float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else None
    return GoldValue(
        variant_id=variant_id, attribute=attr, value_num=num, value_text=None if num is not None else str(raw),
        unit=rules.unit_of(attr), tolerance=tol, tolerance_kind=kind, origin="reference_set",
        match_rule="reference_set", confidence="HIGH", dataset_id=REFERENCE_SET, record_key=record_key,
    )  # fmt: skip
