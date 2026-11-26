"""Spec 013 T002: dialogue-quality expectations of a golden turn — per car the model kept, the level asked, whether
a version was settled without the person's answer; the reply kind; no question repeated; the dialogue stopped."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .runner import TurnObservation
    from .schema import CarExpect, Expect

Question = tuple[str, str, tuple[str, ...]]  # (car key, kind, option labels)
SETTLED = frozenset({"AUTO_OK", "CONFIRMED", "PROPOSED"})


def questions_of(case: dict[str, Any]) -> set[Question]:
    """The questions the case has pending (not a confirmation card): per car, the kind and its option labels."""
    pending = case.get("pending") or {}
    items = pending.get("items") or [] if pending.get("kind") == "QUESTIONS" else []
    return {
        (str(it.get("car") or "*"), str(it.get("kind") or it.get("item") or ""),
         tuple(sorted(str(c.get("label") or c) for c in it.get("choices") or [])))
        for it in items
    }  # fmt: skip


def reply_kind(obs: TurnObservation) -> str:
    """ASK | CONFIRM | REPORT | ANSWER | the action as is."""
    r = obs.result
    if r.status == "WAITING_CONFIRMATION":
        return "CONFIRM"
    action = str(r.action or "")
    return "ANSWER" if action.startswith("ANSWER") else action


def check_quality(obs: TurnObservation, exp: Expect) -> list[str]:
    """The spec 013 expectations of one turn."""
    errs: list[str] = []
    cars = {c.get("key"): c for c in obs.case.get("cars", [])}
    for key, ce in exp.cars.items():
        car = cars.get(key)
        if car is None:
            errs.append(f"{key}: not in the case")
            continue
        errs += [f"{key}: {e}" for e in _check_car(car, ce, obs.case)]
    if exp.reply_kind is not None and (got := reply_kind(obs)) != exp.reply_kind:
        errs.append(f"reply kind {got!r} != {exp.reply_kind!r}")
    if exp.not_repeated and (again := questions_of(obs.case) & obs.asked_before):
        errs.append(f"asked again: {sorted((c, k) for c, k, _ in again)}")
    if exp.stopped:
        errs += _check_stopped(obs)
    reply = obs.result.reply_text or (obs.result.confirm or {}).get("text") or ""
    errs += [f"reply contains {w!r}" for w in exp.reply_not_contains if w in reply]
    return errs


def _check_car(car: dict[str, Any], ce: CarExpect, case: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    for name in ("make", "model", "resolution"):
        want = getattr(ce, name)
        if want is not None and car.get(name) != want:
            errs.append(f"{name} {car.get(name)!r} != {want!r}")
    if ce.identity_state is not None and "identity_state" in car and car["identity_state"] != ce.identity_state:
        errs.append(f"identity_state {car['identity_state']!r} != {ce.identity_state!r}")
    asked = [k for c, k, _ in questions_of(case) if c == car.get("key")]
    if ce.asked_level is not None:
        got = asked[0] if asked else "none"
        if got != ce.asked_level:
            errs.append(f"asked {got!r} != {ce.asked_level!r}")
    if ce.settled is False and car.get("variant_id") and car.get("resolution") in SETTLED and not asked:
        errs.append(f"settled to {car.get('label')!r} without the person's answer")
    for word in ce.label_not_contains:
        for text in (car.get("label"), car.get("model")):
            if text and word in text:
                errs.append(f"{text!r} contains {word!r}")
    return errs


def _check_stopped(obs: TurnObservation) -> list[str]:
    errs: list[str] = []
    if obs.case.get("pending"):
        errs.append(f"still pending: {sorted((c, k) for c, k, _ in questions_of(obs.case))}")
    if obs.result.action == "ASK":
        errs.append("asked again instead of stopping")
    if obs.researched:
        errs.append(f"researched {obs.researched} after stop")
    return errs
