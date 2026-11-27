"""Spec 013 T005: a case's `expect` against what today's path made of the message (`old_path.Observed`).

Each field is True (as expected), False (not), or absent (the case does not check it). The rules are the README's
"What `expect` means": `language`, `answer`, `goals`, `action` always; `reaction` unless `any`; `rejections` and
`changes` when given. A `changes` miss names the sub-fields that differ.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from automind.chat.domain.case import CaseFile
from automind.chat.domain.case.car import CaseCar
from tests.eval.understanding.old_path import Observed
from tests.eval.understanding.schema import CarChange, ChangesExpect, Expected
from tests.eval.understanding.vocab import ReactionExpect

FIELDS = ("language", "answer", "goals", "reaction", "rejections", "changes", "action")


@dataclass(frozen=True)
class Score:
    fields: dict[str, bool]
    misses: dict[str, str] = field(default_factory=dict)  # field -> "expected … got …"

    @property
    def ok(self) -> bool:
        return all(self.fields.values())


def score(e: Expected, o: Observed) -> Score:
    """Every checked field of `e` against `o`."""
    got: dict[str, tuple[bool, str]] = {
        "language": (o.language == e.language.value, f"{e.language.value} / {o.language}"),
        "answer": _answer(e, o),
        "goals": _goals(e, o),
        "action": (o.action == e.action.value, f"{e.action.value} / {o.action}"),
    }
    if e.reaction is not ReactionExpect.ANY:
        want = None if e.reaction is ReactionExpect.NONE else e.reaction.value
        got["reaction"] = (o.reaction == want, f"{want} / {o.reaction}")
    if e.rejections is not None:
        want_r = {(r.car, r.level.value) for r in e.rejections}
        got["rejections"] = (want_r == set(o.rejections), f"{sorted(want_r)} / {sorted(o.rejections)}")
    if e.changes is not None:
        diff = changes_diff(e.changes, o)
        got["changes"] = (not diff, "; ".join(diff))
    return Score({k: v[0] for k, v in got.items()}, {k: v[1] for k, v in got.items() if not v[0]})


def _answer(e: Expected, o: Observed) -> tuple[bool, str]:
    if e.answer is None:
        return o.answer is None, f"none / {o.answer}"
    kind_ok = o.answer is not None and o.answer.value == e.answer.kind.value
    option_ok = e.answer.option_id is None or e.answer.option_id == o.option_id
    return kind_ok and option_ok, f"{e.answer.kind.value}:{e.answer.option_id} / {o.answer}:{o.option_id}"


def _goals(e: Expected, o: Observed) -> tuple[bool, str]:
    want = [g.kind.value for g in e.goals]
    have = [g.value for g in o.goals]
    return want == have, f"{want} / {have}"


def changes_diff(c: ChangesExpect, o: Observed) -> list[str]:
    """The sub-fields of `c` the case after the message does not show ([] = all as expected)."""
    after, before = o.after, o.before
    if c.empty:
        return [] if o.delta_empty and _cars(after) == _cars(before) else ["empty: the case changed"]
    out: list[str] = []
    if c.add_cars is not None:
        added = [_name(x) for x in after.cars if x.key not in {b.key for b in before.cars} and not x.replaced]
        if not _names_match(c.add_cars, added):
            out.append(f"add_cars {c.add_cars} / {added}")
    if c.replaced_car is not None:
        mine = [_name(x) for x in after.cars if x.replaced]
        if not _names_match([c.replaced_car], mine):
            out.append(f"replaced_car {c.replaced_car} / {mine}")
    if c.choose_from_make is not None and _norm(after.wanted_make) != _norm(c.choose_from_make):
        out.append(f"choose_from_make {c.choose_from_make} / {after.wanted_make}")
    for key, want in c.cars.items():
        out += _car_diff(key, want, after, o)
    out += [f"{k} {w} / {g}" for k, w, g in _case_fields(c, after) if w is not None and not _same(w, g)]
    return out


def _car_diff(key: str, want: CarChange, after: CaseFile, o: Observed) -> list[str]:
    car = next((x for x in after.cars if x.key == key), None)
    if car is None:
        return [f"{key}: gone"]
    k, e = car.constraints, car.constraints.engine_hint
    have: dict[str, object] = {
        "make": car.make, "model": car.model, "condition": car.condition, "age_years": car.age_years,
        "year": car.year, "generation": k.generation_hint, "fuel": k.fuel_hint or (e.fuel if e else None),
        "engine": " ".join(x for x in (e.family if e else None, k.version_hint, k.trim_hint) if x) or None,
        "displacement_l": e.displacement_l if e else None, "power_hp": e.power_hp if e else None,
        "power_kw": e.power_kw if e else None, "gearbox": k.gearbox_hint, "drive": k.drive_hint,
        "trim": k.trim_hint, "url": k.url, "replace": key in o.replaced_keys or None,
    }  # fmt: skip
    return [f"{key}.{f} {w} / {have[f]}" for f, w in want.model_dump(exclude_none=True).items()
            if not _same(w, have[f])]  # fmt: skip


_CASE_FIELDS: dict[str, Callable[[CaseFile], object]] = {
    "persona": lambda a: a.persona, "unmapped_wishes": lambda a: bool(a.unmapped_wishes),
    "budget_max_eur": lambda a: a.budget.max_eur, "budget_intent": lambda a: a.budget.intent,
    "running_cost_eur": lambda a: int(a.running_cost_limit.amount_eur) if a.running_cost_limit else None,
    "passengers": lambda a: a.needs.passengers, "luggage_high": lambda a: a.needs.luggage == "HIGH",
    "towing_kg": lambda a: a.needs.towing_kg, "annual_km": lambda a: a.annual_km if a.annual_km_stated else None,
    "ownership_years": lambda a: a.ownership_years, "family": lambda a: a.profile.family,
    "age": lambda a: a.profile.age, "region": lambda a: a.profile.region,
    "home_charging": lambda a: a.profile.home_charging, "race": lambda a: a.race_settings is not None,
    "prediction": lambda a: a.prediction.winner_key if a.prediction else None,
}  # fmt: skip


def _case_fields(c: ChangesExpect, after: CaseFile) -> list[tuple[str, object, object]]:
    rows = [(k, getattr(c, k), get(after)) for k, get in _CASE_FIELDS.items()]
    if c.priorities is not None:
        have = {p.criterion for p in after.priorities}
        rows.append(("priorities", True, set(c.priorities) <= have or sorted(have)))
    if c.usage is not None:
        rows.append(("usage", True, set(c.usage) <= set(after.usage) or sorted(after.usage)))
    return rows


def _cars(case: CaseFile) -> list[dict[str, object]]:
    return [x.model_dump(exclude={"identify", "ladder"}) for x in case.cars]


def _name(car: CaseCar) -> str:
    return " ".join(x for x in (car.make, car.model) if x)


def _names_match(want: list[str], have: list[str]) -> bool:
    """Each expected "Make Model" (or "Make") is the start of the car at the same place."""
    return len(want) == len(have) and all(_norm(h).startswith(_norm(w)) for w, h in zip(want, have, strict=True))


def _norm(s: object) -> str:
    return "".join(ch for ch in str(s or "").casefold() if ch.isalnum())


def _same(want: object, have: object) -> bool:
    if isinstance(want, str) or isinstance(have, str):
        w, h = _norm(want), _norm(have)
        return bool(w) and (w == h or w in h)
    if isinstance(want, float) and isinstance(have, (int, float)):
        return abs(want - have) < 0.05
    return want == have
