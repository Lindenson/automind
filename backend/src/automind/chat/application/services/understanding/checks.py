"""Code checks of the facts a model read from a message (constitution I; moved from `interpretation.interpret`, spec
013 T032): one function per check over a `CaseDelta`, used by the old interpreter and by `validate_understanding`.

Each check either reshapes the delta (a car described under an unknown key is a new car; context for a car added in
the same message belongs to it; the engine from the words is `engine`'s) or drops what the person's words do not
carry (persona and profile without their words, numbers not written in this message, a rejection without its words
or of a value the car does not have) and says so as a `Dropped`. Pure; none raises."""

from __future__ import annotations

from automind.chat.domain import understanding
from automind.chat.domain.case import CarContext, CarRef, CarRejection, CaseDelta, CaseFile, Constraints, current_value
from automind.chat.domain.identification.rejection import RejectLevel, same_value
from automind.chat.domain.understanding.record import Dropped
from automind.shared.vehicle.model_names import match_model

MIN_EVIDENCE = 3  # characters of the person's words a rejection needs
_PROFILE = ("family", "age_band", "driving_style")


def unknown_refs(case: CaseFile, d: CaseDelta) -> list[str]:
    """Car keys the delta refers to that the case does not have (sorted; [] = all known)."""
    keys = {c.key for c in case.cars}
    refs = [*d.remove_cars, *(x.target_key for x in d.replace_cars), *(x.target_key for x in d.set_car_context)]
    if d.set_prediction is not None:
        refs.append(d.set_prediction.winner_key)
    return sorted({r for r in refs if r not in keys})


def fold_new_car_context(case: CaseFile, d: CaseDelta) -> CaseDelta:
    """Context for a car added in the same message ("car#1" while the case has none yet; live run 2026-11-04,
    Gemini) belongs to that new car: its condition, year or hints are folded into the add, not an error."""
    keys = {c.key for c in case.cars}
    new = {f"car#{case.next_car_no + n}": ref for n, ref in enumerate(d.add_cars)}
    keep = []
    for ctx in d.set_car_context:
        ref = new.get(ctx.target_key) if ctx.target_key not in keys else None
        if ref is None:
            keep.append(ctx)
            continue
        for f in ("condition", "year", "age_years", "mileage_km"):
            v = getattr(ctx, f, None)
            if v is not None and (getattr(ref, f) in (None, "UNKNOWN")):
                setattr(ref, f, v)
    if len(keep) == len(d.set_car_context):
        return d
    return d.model_copy(update={"set_car_context": keep})


def unknown_targets_as_new_cars(case: CaseFile, d: CaseDelta) -> CaseDelta:
    """A car described for a key the case does not have is a new car, not an error (009 FR-022, chat 20b5b7f9: the
    first message "a Kia to replace my Prado 150" came back as replace_cars of car#1 in an empty case). Only a
    description with a make or a model is kept."""
    keys = {c.key for c in case.cars}
    stray = [x for x in (*d.replace_cars, *d.set_car_context) if x.target_key not in keys and (x.make or x.model)]
    if not stray:
        return d
    add = [_as_new_car(x) for x in stray]
    gone = {id(x) for x in stray}
    return d.model_copy(update={
        "add_cars": [*d.add_cars, *add],
        "replace_cars": [x for x in d.replace_cars if id(x) not in gone],
        "set_car_context": [x for x in d.set_car_context if id(x) not in gone],
    })  # fmt: skip


def persona_from_words(d: CaseDelta, evidence: str | None, said: list[str]) -> tuple[CaseDelta, list[Dropped]]:
    """A persona needs the person's own words (spec 007 FR-002). Words from an earlier message only are an
    inference: INFERRED, which never overwrites what the person stated or set in the panel."""
    p = d.set_persona
    if p is None:
        return d, []
    if not _said(evidence, said):
        why = f"persona {p.persona}: the words {evidence!r} are not the person's"
        return d.model_copy(update={"set_persona": None}), [Dropped(check="persona_words", field="set_persona",
                                                                     why=why)]  # fmt: skip
    if _said(evidence, said[:1]):
        return d, []
    basis = {**d.profile_basis, "persona": "INFERRED"}
    return d.model_copy(update={"set_persona": p.model_copy(update={"source": "INFERRED"}),
                                "profile_basis": basis}), []  # fmt: skip


def profile_from_words(d: CaseDelta, said: list[str]) -> tuple[CaseDelta, list[Dropped]]:
    """Profile fields (family, age band, driving style) need words the person wrote (constitution I); words from an
    earlier message only are INFERRED."""
    p = d.set_profile
    if p is None:
        return d, []
    keep = {f: w for f, w in p.evidence.items() if _said(w, said)}
    gone = [f for f in _PROFILE if getattr(p, f) is not None and f not in keep]
    basis = dict(d.profile_basis)
    for f, w in keep.items():
        if f in _PROFILE and not _said(w, said[:1]):
            basis[f] = "INFERRED"
    update = {"set_profile": p.model_copy(update={**dict.fromkeys(gone), "evidence": keep}), "profile_basis": basis}
    dropped = [Dropped(check="profile_words", field=f"set_profile.{f}", why="no words of the person say it")
               for f in gone]  # fmt: skip
    return d.model_copy(update=update), dropped


def constraints_from_message(d: CaseDelta, text: str) -> tuple[CaseDelta, list[Dropped]]:
    """Numbers in budget, running-cost limit and needs must be written in THIS message (constitution I): an amount
    the model inferred or took from history is dropped; an intent-only budget answer is kept."""
    seen = understanding.amounts_in(text)

    def ok(v: float | None) -> bool:
        return v is None or any(abs(v - n) <= max(1.0, 0.005 * n) for n in seen)

    upd: dict[str, object] = {}
    dropped: list[Dropped] = []
    if d.set_budget is not None and not ok(d.set_budget.max_eur):
        upd["set_budget"] = (
            d.set_budget.model_copy(update={"max_eur": None}) if d.set_budget.intent != "UNKNOWN" else None
        )
        dropped.append(_not_written("set_budget.max_eur", d.set_budget.max_eur))
    if d.set_running_cost_limit is not None and not ok(d.set_running_cost_limit.amount_eur):
        upd["set_running_cost_limit"] = None
        dropped.append(_not_written("set_running_cost_limit", d.set_running_cost_limit.amount_eur))
    if d.set_needs is not None:
        n = d.set_needs
        bad = {k: None for k in ("passengers", "towing_kg", "daily_km") if not ok(getattr(n, k))}
        if bad:
            kept = n.model_copy(update=bad)
            upd["set_needs"] = kept if kept.model_dump(exclude_none=True, exclude_defaults=True) else None
            dropped += [_not_written(f"set_needs.{k}", getattr(n, k)) for k in bad]
    return (d.model_copy(update=upd) if upd else d), dropped


def heard_rejections(case: CaseFile, d: CaseDelta, text: str) -> tuple[CaseDelta, list[Dropped]]:
    """Only the rejections code can stand behind (spec 013 S2, T021): the car exists, the person's words are in the
    message, the value rejected is the car's current one (or left to it) and not the one they want, and a model is
    never rejected when it is the one the person asked for (their request names it) unless they name another. The
    delta is returned as it is when every rejection stands."""
    if not d.rejections:
        return d, []
    kept = [r for r in d.rejections if _stands(case, r, text)]
    if len(kept) == len(d.rejections):
        return d, []
    dropped = [Dropped(check="heard_rejections", field=f"rejections.{r.target_key}.{r.level}",
                       why=f"{r.value or 'the current value'} cannot be rejected by {r.evidence!r}")
               for r in d.rejections if r not in kept]  # fmt: skip
    return d.model_copy(update={"rejections": kept}), dropped


def _stands(case: CaseFile, r: CarRejection, text: str) -> bool:
    car = next((c for c in case.cars if c.key == r.target_key), None)
    if car is None or not _in_message(r.evidence, text):
        return False
    now = current_value(car, r.level)
    if not now or (r.value and not same_value(r.value, now)):
        return False  # nothing there to reject, or the model names a value the car does not have
    if same_value(r.wanted, now):
        return False  # "you did not find the C-Class" while the car is the C-Class
    # I1, the person's words win: the model they asked for is not rejected unless they name another one
    return not (r.level is RejectLevel.MODEL and not r.wanted and match_model(car.request_text, [now]) is not None)


def _as_new_car(x: CarContext) -> CarRef:
    return CarRef(request_text=x.request_text or " ".join(p for p in (x.make, x.model) if p), make=x.make,
                  model=x.model, condition=x.condition or "UNKNOWN", year=x.year, age_years=x.age_years,
                  mileage_km=x.mileage_km, constraints=x.constraints or Constraints())  # fmt: skip


def _not_written(field: str, value: object) -> Dropped:
    return Dropped(check="numbers_in_message", field=field, why=f"{value} is not written in the message")


def _in_message(words: str, text: str) -> bool:
    w, t = " ".join(words.lower().split()), " ".join(text.lower().split())
    return len(w) >= MIN_EVIDENCE and w in t


def _norm(t: str) -> str:
    return " ".join(t.lower().split())


def _said(words: str | None, said: list[str]) -> bool:
    """The words (3+ characters) appear in one of the person's messages, case and spacing ignored."""
    return words is not None and len(words.strip()) >= 3 and any(_norm(words) in _norm(t) for t in said)
