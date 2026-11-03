"""Intake loop (spec 005 R5, R6, R11, R12). Pure and deterministic.

- `identity_key`: what makes a car this car; a change re-identifies it (corrections, FR-013).
- `progress`: did a reply move the identification forward (a fact changed, or the identify outcome improved)?
- `next_step`: the next intake step — ASK (≤ 3 items, rephrased when asked before), PROPOSE (after 2 attempts on
  one item), REMOVE_OR_CHOOSE (after 4 on one car), CARD (everything identified), NONE (card confirmed).
- `record_asked` / `is_repeat`: the same question (car, item, text) is never sent twice (FR-003).
- `parse_distance`: "1–2 тыс км в месяц" → 12,000–24,000 km a year (FR-016).
- `rank_lineup`: 1–3 models of a make that fit the person, with machine reasons (FR-008).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from .casefile import CaseCar, CaseFile, Choice, IdentifyKind, IntakeItem

StepKind = Literal["ASK", "PROPOSE", "REMOVE_OR_CHOOSE", "CARD", "NONE"]
ALL = "*"  # attempts key for questions about every car (CONDITION)
MAX_ITEMS = 3
_RANK: dict[str | None, int] = {None: 0, "NEED": 1, "NOT_FOUND": 1, "CHOICES": 2, "IDENTIFIED": 3}


@dataclass(frozen=True)
class Limits:
    max_attempts_per_item: int = 2
    max_attempts_per_car: int = 4
    full_intake: bool = True  # ask new/used for every car and the year of used ones (US4)


@dataclass(frozen=True)
class StepItem:
    item: IntakeItem
    car_key: str | None  # None: a question about every car (CONDITION)
    rephrase: bool = False  # asked before: other words and concrete options
    choices: tuple[Choice, ...] = ()


@dataclass(frozen=True)
class Step:
    kind: StepKind
    items: tuple[StepItem, ...] = ()
    car_key: str | None = None  # PROPOSE / REMOVE_OR_CHOOSE


def identity_key(car: CaseCar) -> tuple[object, ...]:
    k = car.constraints
    e = k.engine_hint
    engine = (e.displacement_l, e.power_kw, e.fuel, (e.family or "").lower()) if e and not e.empty() else None
    return ((car.make or "").lower(), (car.model or "").lower(), (k.generation_hint or "").lower(), engine,
            k.gearbox_hint, k.drive_hint, car.year, car.age_years, car.condition, (k.trim_hint or "").lower(),
            k.fuel_hint, k.url)  # fmt: skip


def progress(before: CaseCar | None, after: CaseCar | None, outcome_before: str | None,
             outcome_after: str | None) -> bool:  # fmt: skip
    if before is None or after is None:
        return True  # a car was added or removed
    if identity_key(before) != identity_key(after):
        return True
    return _RANK.get(outcome_after, 0) > _RANK.get(outcome_before, 0)


def _need(car: CaseCar) -> IntakeItem | None:
    """What is still missing for this car (None: identified)."""
    o = car.identify
    if not car.make:
        return "MAKE"
    if not car.model:
        return o.need if o and o.need in ("MODEL", "CHOICE") else "MODEL"
    if o is None:
        return None  # not identified yet in this turn (a case before 005, or a 4th car): the policy rules decide
    outcome: IdentifyKind = o.outcome
    if outcome == "IDENTIFIED":
        return None
    if outcome == "CHOICES":
        return o.need or "CHOICE"
    return o.need or "MODEL"


def next_step(case: CaseFile, limits: Limits = Limits()) -> Step:  # noqa: B008 - frozen dataclass
    items: list[StepItem] = []
    for car in case.cars:
        item = _need(car)
        if item is None:
            continue
        total = sum(case.intake.attempts.get(car.key, {}).values())
        if (
            total >= limits.max_attempts_per_car
            or case.intake.attempt(car.key, "CHOICE") >= limits.max_attempts_per_item
        ):
            return Step("REMOVE_OR_CHOOSE", car_key=car.key)
        n = case.intake.attempt(car.key, item)
        if n >= limits.max_attempts_per_item:
            return Step("PROPOSE", car_key=car.key)
        choices = tuple(car.identify.choices) if car.identify else ()
        items.append(StepItem(item, car.key, rephrase=n >= 1, choices=choices))
    if limits.full_intake and items:  # asked together with an identity question, never on its own (FR-018)
        items += _condition_and_year(case, limits)
    if items:
        return Step("ASK", tuple(items[:MAX_ITEMS]))
    if not case.cars or case.intake.card_confirmed:
        return Step("NONE")
    return Step("CARD")


def _condition_and_year(case: CaseFile, limits: Limits) -> list[StepItem]:
    """New or used, asked once for every car together; then year (and mileage) of each used car."""
    n = case.intake.attempt(ALL, "CONDITION")
    if any(c.condition == "UNKNOWN" for c in case.cars) and n < limits.max_attempts_per_item:
        return [StepItem("CONDITION", None, rephrase=n >= 1)]
    out = []
    for car in case.cars:
        n = case.intake.attempt(car.key, "YEAR")
        if car.condition == "USED" and car.year is None and car.age_years is None and n < limits.max_attempts_per_item:
            out.append(StepItem("YEAR", car.key, rephrase=n >= 1))
    return out


def question_hash(car_key: str | None, item: str, text: str) -> str:
    norm = " ".join(text.lower().split())
    return hashlib.sha1(f"{car_key or ALL}|{item}|{norm}".encode()).hexdigest()[:12]


def is_repeat(case: CaseFile, car_key: str | None, item: str, text: str) -> bool:
    return question_hash(car_key, item, text) in case.intake.last_questions


def record_asked(case: CaseFile, asked: Iterable[tuple[StepItem, str]]) -> CaseFile:
    """Remember what was asked: attempts +1 per item, the text hashes (≤ 6, newest last)."""
    c = case.model_copy(deep=True)
    for it, text in asked:
        c.intake.bump(it.car_key or ALL, it.item)
        c.intake.last_questions = [*c.intake.last_questions, question_hash(it.car_key, it.item, text)][-6:]
    return c


# --- the person: region, new or used (R11) -----------------------------------------------------------------

_NEW = re.compile(r"\b(нов\w*|new|nuev\w*|0 ?km|с нуля|из салона)\b", re.I)
_USED = re.compile(
    r"(подержан\w*|\bб/у\b|\bбу\b|с пробегом|\bused\b|second[- ]hand|segunda mano|ocasi[oó]n|seminuev\w*)", re.I
)


def condition_of(text: str | None) -> str | None:
    """NEW / USED from a short answer ("новые", "б/у", "de segunda mano"); None when the text says neither."""
    if not text:
        return None
    used, new = bool(_USED.search(text)), bool(_NEW.search(text))
    if used == new:
        return None
    return "USED" if used else "NEW"


def region_of(text: str | None, regions: dict[str, dict[str, object]]) -> tuple[str, str, str] | None:
    """(code, climate, the words) of the most specific region named in the text (the longest name wins)."""
    if not text:
        return None
    low = text.lower()
    best: tuple[int, str, str, str] | None = None
    for code, info in regions.items():
        for name in info.get("names") or []:  # type: ignore[attr-defined]
            n = str(name).lower()
            if re.search(rf"(?<![\w]){re.escape(n)}(?![\w])", low) and (best is None or len(n) > best[0]):
                best = (len(n), code, str(info.get("climate")), n)
    return (best[1], best[2], best[3]) if best else None


# --- distances ---------------------------------------------------------------------------------------------

_NUM = r"\d{1,3}(?:[  .]\d{3})+|\d+(?:[.,]\d+)?"
_DIST = re.compile(
    rf"({_NUM})(?:\s*[-–—]\s*({_NUM}))?\s*(тыс\w*\.?|k\b|mil\b)?\s*(?:км|km|kil[oó]metr\w*)?\.?\s*"
    r"(?:в|al|a|per|/|за)\s*(месяц|mes|month|год|año|ano|year)",
    re.I,
)
_PERIOD_MONTH = ("месяц", "mes", "month")


def _num(s: str) -> float:
    s = s.replace(" ", " ").strip()
    if re.fullmatch(r"\d{1,3}(?:[ .]\d{3})+", s):
        return float(re.sub(r"[ .]", "", s))
    return float(s.replace(",", "."))


def parse_distance(text: str | None) -> tuple[int, int] | None:
    """A yearly distance (min, max) in km from the user's words, or None. A mileage without a period is not it."""
    if not text:
        return None
    m = _DIST.search(text)
    if not m:
        return None
    lo = _num(m.group(1))
    hi = _num(m.group(2)) if m.group(2) else lo
    mult = 1000.0 if m.group(3) else 1.0
    per_year = 12.0 if m.group(4).lower() in _PERIOD_MONTH else 1.0
    a, b = round(lo * mult * per_year), round(hi * mult * per_year)
    if not (1000 <= a <= 200000 and 1000 <= b <= 200000):
        return None
    return (min(a, b), max(a, b))


# --- "find the matching model" (R12) -----------------------------------------------------------------------

_FAMILY_BODIES = ("suv", "estate", "mpv", "crossover", "familiar", "monovolumen", "todocamino")
_SMALL_BODIES = ("city", "hatch", "urbano", "mini")


@dataclass(frozen=True)
class LineupModel:
    model: str
    body: str = ""
    powertrains: tuple[str, ...] = ()  # petrol, diesel, hybrid, mhev, phev, bev
    price_from_eur: int | None = None
    source_url: str | None = None


@dataclass(frozen=True)
class Fit:
    family: bool = False
    annual_km: int | None = None
    priorities: tuple[str, ...] = ()
    budget_eur: int | None = None
    reference_price_eur: int | None = None  # price of the other compared car (same segment ± 30 %)
    reasons_lang: str = "en"
    extra: dict[str, str] = field(default_factory=dict)


def _score(m: LineupModel, fit: Fit) -> tuple[float, list[str]]:
    score, why = 0.0, []
    body = m.body.lower()
    if fit.family:
        if any(b in body for b in _FAMILY_BODIES):
            score += 3
            why.append("family_body")
        elif any(b in body for b in _SMALL_BODIES):
            score -= 2
    km = fit.annual_km or 15000
    thrifty = any(p in fit.priorities for p in ("efficiency", "ownership_cost"))
    pts = set(m.powertrains)
    if thrifty or km >= 15000:
        if "phev" in pts:
            score += 2
            why.append("phev_low_running_cost")
        elif "hybrid" in pts or "bev" in pts:
            score += 1.5
            why.append("bev_low_running_cost" if "bev" in pts else "hybrid_low_running_cost")
    ref = fit.budget_eur or fit.reference_price_eur
    if ref and m.price_from_eur:
        ratio = m.price_from_eur / ref
        if 0.7 <= ratio <= 1.3:
            score += 1.5
            why.append("price_close")
        elif ratio > 1.5:
            score -= 2
    return score, why


def rank_lineup(models: Sequence[LineupModel], fit: Fit, limit: int = 3) -> list[tuple[LineupModel, list[str]]]:
    """Top models of a line-up for the person, each with machine reason keys (phrased by the caller). A model
    priced over 1.3 × the user's own budget is never proposed."""
    cap = fit.budget_eur * 1.3 if fit.budget_eur else None
    pool = [m for m in models if not (cap and m.price_from_eur and m.price_from_eur > cap)]
    family = [m for m in pool if any(b in m.body.lower() for b in _FAMILY_BODIES)]
    if fit.family and family:  # a family is offered family-size bodies only
        pool = family
    scored = [(_score(m, fit), m) for m in pool]
    scored.sort(key=lambda x: (-x[0][0], x[1].price_from_eur or 10**9, x[1].model))
    return [(m, why) for (s, why), m in scored[:limit] if s > -2]


# --- spec 007 F: a tapped option is the answer (incident 2026-11-03, Mazda CX-5 asked five times) -------------


def _plain_text(s: str | None) -> str:
    return " ".join(re.sub(r"[^\w+.\-()]", " ", (s or "").lower()).split())


def _without(label: str, *words: str | None) -> str:
    out = label
    for w in sorted({x for x in words if x}, key=len, reverse=True):
        out = re.sub(rf"(?i)(?<![\w]){re.escape(w)}(?![\w])", " ", out)
    return " ".join(out.split())


def _apply_choice(car: CaseCar, ch: Choice) -> str:
    """The user picked this option: it replaces what an earlier option left behind (generation, engine, version)."""
    from .identity import parse_engine  # local import: identity imports casefile lazily

    k = car.constraints
    k.generation_hint = k.engine_hint = k.trim_hint = None
    car.make = ch.make or car.make
    car.model = ch.model or car.model
    car.identify = None
    if ch.variant_id:
        car.variant_id, car.label, car.resolution = ch.variant_id, ch.label, "CONFIRMED"
        return f"{car.key}: {ch.label} (picked)"
    car.variant_id, car.label, car.resolution = None, None, "UNRESOLVED"
    rest = _without(ch.label, car.make, car.model)
    if ch.variant_id is None and rest and (e := parse_engine(rest)) is not None and not e.empty():
        k.engine_hint = e
    return f"{car.key}: {ch.label} (picked)"


def pick(case: CaseFile, text: str, *, gearbox_words: dict[str, str], yes: bool = False,
         choose: bool = False) -> tuple[CaseFile, list[str]] | None:  # fmt: skip
    """A reply that is exactly one of the offered options (a tapped chip, or the option typed) answers the pending
    question by code, without the interpreter: the option's variant, model or engine is set and the hints left by
    an earlier option are dropped. "Yes" to a proposal takes the proposed option; "choose for me" on a gearbox
    question takes the automatic. Returns None when the reply is not an offered option."""
    p = case.pending
    if p is None or p.kind != "QUESTIONS":
        return None
    said = _plain_text(text)
    if not said:
        return None
    new = case.model_copy(deep=True)
    for item in p.items:
        key = str(item.get("car") or "")
        if not key or not any(c.key == key for c in new.cars):
            continue
        car = new.car(key)
        kind = item.get("kind")
        if kind == "GEARBOX":
            gb = gearbox_words.get(said) or ("automatic" if choose else None)
            if gb:
                car.constraints.gearbox_hint = gb  # type: ignore[assignment]
                return new, [f"{key}: gearbox {gb}"]
            continue
        raw = item.get("choices")
        choices = [Choice.model_validate(x) for x in raw] if isinstance(raw, list) else []
        if kind == "PROPOSE" and yes and choices:
            return new, [_apply_choice(car, choices[0])]
        hit = next((ch for ch in choices if _plain_text(ch.label) == said), None)
        if hit is not None:
            return new, [_apply_choice(car, hit)]
    return None


def inherit_condition(before: CaseFile, after: CaseFile) -> list[str]:
    """A car added later in the chat ("and the Mazda?") is bought like the cars already compared: when they all
    share a condition (and, if new, a year), the added car takes it instead of asking "new or used?" again."""
    old = {c.key for c in before.cars}
    others = [c for c in after.cars if c.key in old]
    conds = {c.condition for c in others}
    if len(conds) != 1 or "UNKNOWN" in conds:
        return []
    cond = next(iter(conds))
    years = {c.year for c in others}
    log = []
    for car in after.cars:
        if car.key in old or car.condition != "UNKNOWN":
            continue
        car.condition = cond
        if cond == "NEW" and len(years) == 1 and car.year is None:
            car.year = next(iter(years))
        log.append(f"{car.key}: {cond.lower()} like the other cars")
    return log
