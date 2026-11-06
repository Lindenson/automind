"""The person own consumption figures in their words (spec 006 follow-up): litres, kWh per 100 km, charge-sustaining
and electric figures, per car."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from automind.chat.domain.understanding.charging import any_match

_FIGURE = r"(\d{1,3}(?:[.,]\d{1,2})?)"  # a consumption or distance figure: "6,5", "18"


_PER_100 = r"\s*(?:/|на|per|a\s+los|por|cada|every)\s*100(?!\d)"


_LITRES = re.compile(_FIGURE + r"\s*(?:l|л|литр\w*|litros?|lit(?:er|re)s?)(?!\w)(" + _PER_100 + r")?", re.I)


_KWH_100 = re.compile(_FIGURE + r"\s*(?:kwh|квт\W?ч|квтч|кв\W?ч)(" + _PER_100 + r")?", re.I)


_KM = re.compile(_FIGURE + r"\s*(?:km|км)(?!\s*/\s*[hч])(?!\w)", re.I)


_CONSUMPTION = (r"расход", r"\bест\b", r"жр[её]т", r"потребля", r"тратит", r"consum", r"gasta", r"\buses\b",
                r"burns", r"real", r"реальн")  # fmt: skip


_CS_WORDS = (r"гибридн\w* режим", r"разряж", r"пуст\w* батаре", r"сел\w* батаре", r"без заряд", r"на бензине",
             r"empty battery", r"battery (?:is )?empty", r"flat battery", r"hybrid mode", r"charge.sustaining",
             r"modo h[ií]brido", r"bater[ií]a (?:vac[ií]a|descargada|agotada)", r"sin bater[ií]a",
             r"sin carga")  # fmt: skip


_EV_WORDS = (r"электр", r"на батаре", r"electric", r"on battery", r"ev mode", r"el[ée]ctric", r"modo ev",
             r"en el[ée]ctrico")  # fmt: skip


_PER_PERIOD = (r"в день", r"в сутки", r"ежеднев", r"в год", r"в неделю", r"в месяц", r"a day", r"per day", r"daily",
               r"a year", r"per year", r"a week", r"al d[ií]a", r"diari", r"al a[ñn]o", r"a la semana", r"/d[ií]a",
               r"/day")  # fmt: skip


_CLAUSE = re.compile(r"[.;!?\n]+(?:\s|$)|,\s|\s(?:а|но|and|but|while|y|pero|mientras)\s")


BOUNDS = {"FUEL": (2.0, 30.0), "CS": (2.0, 20.0), "KWH": (8.0, 45.0), "RANGE": (10.0, 1000.0)}


@dataclass(frozen=True)
class EnergyFigure:
    kind: Literal["FUEL", "CS", "KWH", "RANGE"]
    value: float
    words: str  # the clause it was read from
    start: int  # where the number is in the message (for finding the car named before it)


def _near(patterns: tuple[str, ...], low: str, a: int, b: int) -> bool:
    return any_match(patterns, low[max(0, a) : max(0, b)]) is not None


def energy_figures_of(text: str | None) -> list[EnergyFigure]:
    """Consumption figures the user states: "в гибридном режиме 5,5 л", "Ateca gasta 7,5 l/100 km",
    "18 кВт·ч на 100", "на электричестве проезжаю 70 км". A litre or kWh number counts only after a consumption
    word or with "per 100" (an engine "1.5 л" or a battery "18 кВт·ч" is not a consumption); km only next to an
    electric word and not "a day"; values outside plausible bounds are dropped."""
    out: list[EnergyFigure] = []
    if not text:
        return out
    low = text.lower()
    bounds = [0] + [m.end() for m in _CLAUSE.finditer(low)] + [len(low)]
    for lo, hi in zip(bounds, bounds[1:], strict=False):
        clause = low[lo:hi]
        words = text[lo:hi].strip()[:120]
        for m in _LITRES.finditer(clause):
            a, b = m.start(), m.end()
            cs = _near(_CS_WORDS, clause, a - 45, b + 45)
            if not (m.group(2) or cs or _near(_CONSUMPTION, clause, a - 40, a)):
                continue
            out.append(EnergyFigure("CS" if cs else "FUEL", float(m.group(1).replace(",", ".")), words, lo + a))
        for m in _KWH_100.finditer(clause):
            a = m.start()
            if m.group(2) or _near(_CONSUMPTION, clause, a - 40, a):
                out.append(EnergyFigure("KWH", float(m.group(1).replace(",", ".")), words, lo + a))
        for m in _KM.finditer(clause):
            a, b = m.start(), m.end()
            if clause[b : b + 6].lstrip().startswith(("/", "на 100", "per 100")) or _near(
                _PER_PERIOD, clause, b, b + 14
            ):
                continue
            if _near(_EV_WORDS, clause, a - 45, b + 30):
                out.append(EnergyFigure("RANGE", float(m.group(1).replace(",", ".")), words, lo + a))
    return [f for f in out if BOUNDS[f.kind][0] <= f.value <= BOUNDS[f.kind][1]]


APPLIES = {"FUEL": ("ICE", "MHEV", "HEV"), "CS": ("PHEV", "EREV"), "KWH": ("BEV", "PHEV", "EREV"),
           "RANGE": ("BEV", "PHEV", "EREV")}  # fmt: skip


def stated_for_cars(stated: Sequence[object], cars: Sequence[tuple[str, str | None]]
                    ) -> dict[str, dict[str, tuple[float, str]]]:  # fmt: skip
    """{car key: {kind: (value, words)}} — a figure goes to the car it names when it fits that car's powertrain,
    else to the one car it can apply to (a charge-sustaining figure with one plug-in in the comparison); a figure
    that fits no car or several is not used. The newest figure of a kind wins."""
    out: dict[str, dict[str, tuple[float, str]]] = {}
    pts = {k: (pt or "ICE").upper() for k, pt in cars}
    for f in stated:
        kind, key = getattr(f, "kind"), getattr(f, "car_key")  # noqa: B009 - a StatedEnergy
        fits = [k for k, pt in pts.items() if pt in APPLIES[kind]]
        # the named car when the figure fits it; else the only car it fits ("Ateca, 5,5 л в гибридном режиме":
        # Ateca has no hybrid mode, the plug-in next to it does)
        target = key if key in pts and pts[key] in APPLIES[kind] else (fits[0] if len(fits) == 1 else None)
        if target is not None:
            out.setdefault(target, {})[kind] = (float(getattr(f, "value")), str(getattr(f, "words")))  # noqa: B009
    return out
