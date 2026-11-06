"""Ranking the models of a make and the candidates for a person: body words, scores with machine reasons (FR-008, spec
007 US7)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from automind.chat.domain.case.fit import Fit

_FAMILY_BODIES = ("suv", "estate", "mpv", "crossover", "familiar", "monovolumen", "todocamino")


_SMALL_BODIES = ("city", "hatch", "urbano", "mini")


@dataclass(frozen=True)
class LineupModel:
    model: str
    body: str = ""
    powertrains: tuple[str, ...] = ()  # petrol, diesel, hybrid, mhev, phev, bev
    price_from_eur: int | None = None
    source_url: str | None = None
    country: str | None = None  # a European line-up: the country whose page lists it ("PL"), when its domain says


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


BODY_WORDS: dict[str, tuple[str, ...]] = {
    "suv": ("кроссовер", "кроссовера", "кроссоверы", "внедорожник", "паркетник", "джип", "suv", "crossover",
            "todocamino", "todoterreno"),
    "estate": ("универсал", "estate", "wagon", "familiar", "touring", "sportstourer"),
    "mpv": ("минивэн", "минивен", "компактвэн", "mpv", "monovolumen", "minivan"),
    "sedan": ("седан", "sedan", "saloon", "berlina"),
    "hatchback": ("хэтчбек", "хетчбек", "hatchback", "compacto"),
}  # fmt: skip


_BODY_MATCH = {"suv": ("suv", "crossover", "todocamino", "4x4"), "estate": ("estate", "familiar", "wagon", "touring"),
               "mpv": ("mpv", "monovolumen", "van"), "sedan": ("sedan", "berlina", "saloon"),
               "hatchback": ("hatchback", "compacto")}  # fmt: skip


def body_class_of(body: str | None) -> str | None:
    """A line-up or catalog body ("SUV", "todocamino", "familiar") as a body class the candidates use, or None."""
    low = (body or "").lower()
    return next((b for b, ws in _BODY_MATCH.items() if any(w in low for w in ws)), None) if low else None


def body_of(text: str) -> str | None:
    """The body class named in the user's words ("семейный кроссовер" → suv), or None."""
    words = set(re.findall(r"[\w-]+", (text or "").lower()))
    return next((b for b, ws in BODY_WORDS.items() if words & set(ws)), None)


def pick_candidates(pool: Sequence[tuple[str, LineupModel]], fit: Fit, body: str | None,
                    limit: int = 3) -> list[tuple[str, LineupModel, list[str]]]:  # fmt: skip
    """2–3 models for the person: of the body asked, within the budget (a model without a price only when there
    are not enough priced ones; the caller shows "price to check"), ranked by `rank_lineup` reasons, one per make
    first. Returns (make, model, reason keys)."""
    want = _BODY_MATCH.get(body or "", ())
    shaped = [(mk, m) for mk, m in pool if not want or any(w in m.body.lower() for w in want)]
    budget = fit.budget_eur
    priced = [(mk, m) for mk, m in shaped if m.price_from_eur and (not budget or m.price_from_eur <= budget)]
    unpriced = [(mk, m) for mk, m in shaped if not m.price_from_eur]
    make_of = {id(m): mk for mk, m in [*priced, *unpriced]}
    out: list[tuple[str, LineupModel, list[str]]] = []
    for group in (priced, unpriced):
        ranked = rank_lineup([m for _, m in group], fit, limit=len(group))
        for one_per_make in (True, False):
            for m, why in ranked:
                mk = make_of[id(m)]
                if len(out) >= limit or any(o[1] is m for o in out):
                    continue
                if one_per_make and any(o[0] == mk for o in out):
                    continue
                out.append((mk, m, why))
        if len(out) >= 2:
            break
    return out[:limit]
