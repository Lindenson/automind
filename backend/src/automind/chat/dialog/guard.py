"""Number guard (FR-031): every number in AI-written text must exist in validated or computed data.

A written number matches a fact when the fact, rounded to the precision the number is written with, equals it
(spec 016 T302): "9,8" matches 9.75, "42 500" matches 42 480, "205" does not match 204, and an integer below 1000 is
exact ("10" never stands for 6.7, FR-033). Names of metrics ("0–100
km/h", "l/100 km") are cut before the check (T301), numbers inside model codes ("D-4D", "J250") are names on both
sides, and every check splits sentences the same way, never after an abbreviation such as "л.с." (T303)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from automind.chat.application.services.report.contracts import CheckInput

# A number as written in any of our languages: "25 000", "25.000", "25,000", "1.234,5", "6,58", "20k", "20 тыс".
_NUM = r"\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)*"
_MULT = r"(?:\s?([kк](?![a-zа-яё])|тыс\.?|mil\b|thousand))?"
# Numbers inside model codes (J250, Mk8, F30, i30, D-4D) are names, not figures: never checked in the text.
_CHECKED_RE = re.compile(rf"(?<![A-Za-z])(?<![A-Za-z]-)(?<![\d.,])({_NUM}){_MULT}", re.I)
# In the facts a generation code gives its number ("J150" → 150: the text may write "Prado 150"), an engine code
# with a hyphen does not ("2.8 D-4D" puts no 4 in the facts, spec 016 T301).
_FACT_RE = re.compile(rf"(?<![A-Za-z]-)(?<![\d.,])({_NUM}){_MULT}", re.I)

# --- contracts: the closed tables of the guard (spec 016 T301, T303) -------------------------------------------
# Names of metrics: their numbers are part of the name, not figures ("0–100 km/h", "l/100 km"). Cut before the check.
METRIC_NAMES = ("0-100 km/h", "0-100 км/ч", "0-200 km/h", "0-200 км/ч", "0-100", "0-200", "0-62 mph",
                "400 m", "400 м", "l/100 km", "л/100 км", "kWh/100 km", "кВт·ч/100 км", "kWh/100km", "/100 km",
                "/100 км", "на 100 км", "per 100 km", "por 100 km", "a los 100 km")  # fmt: skip
# Abbreviations after which a period does not end a sentence.
ABBREVIATIONS = ("л.с.", "т.д.", "т.е.", "т.к.", "т.п.", "г.", "гг.", "e.g.", "i.e.", "approx.", "aprox.", "etc.",
                 "vs.", "p.ej.")  # fmt: skip


def readings(token: str, mult: str | None = None) -> set[float]:
    """Every value a written number can mean: "25.000" is 25,000 in Spanish and 25.0 in English, so both are
    kept; "25 000" is one number, never 25 and 0 (reviewer 2026-11-03: "25 000 €" failed the check)."""
    raw = re.sub(r"[ \u00a0\u202f]", "", token)
    seps = re.findall(r"[.,]", raw)
    out: set[float] = set()
    try:
        if not seps:
            out.add(float(raw))
        elif len(set(seps)) == 2:  # "1.234,5" / "1,234.5": the last one is the decimal mark
            dec = raw[max(raw.rfind("."), raw.rfind(","))]
            out.add(float(raw.replace("," if dec == "." else ".", "").replace(",", ".")))
        elif len(seps) > 1:  # "1.234.567"
            if all(len(g) == 3 for g in re.split(r"[.,]", raw)[1:]):
                out.add(float(re.sub(r"[.,]", "", raw)))
        else:
            head, tail = re.split(r"[.,]", raw)
            out.add(float(f"{head}.{tail}"))
            if len(tail) == 3:
                out.add(float(head + tail))
    except ValueError:
        return set()
    if mult:
        out = {x * 1000 for x in out}
    return out


_METRIC_RE = re.compile(r"(?<![\w.,])(?:" + "|".join(
    re.escape(n).replace("\\-", "[-–—]").replace("\\ ", r"\s?").replace("/", r"\s?/\s?")
    for n in sorted(METRIC_NAMES, key=len, reverse=True)) + r")(?!\w)", re.I)  # fmt: skip
_ABBREV_RE = re.compile(r"(?:^|(?<=[\s(]))(?:" + "|".join(re.escape(a) for a in sorted(ABBREVIATIONS, key=len,
                        reverse=True)) + r")$", re.I)  # fmt: skip


_MONEY_AROUND = re.compile(r"(?:€|EUR)\s?$|^\s?(?:€|EUR)", re.I)
_THOUSANDS_ONLY = re.compile(r"\d{1,3}[.,]\d{3}")
_SEPARATOR = re.compile(r"[.,]")
_STOP_RE = re.compile(r"[.!?]\s+")


def sentences(line: str) -> list[str]:
    """The sentences of one line: split after ".", "!" or "?" and a space, except after an abbreviation of
    `ABBREVIATIONS` ("204 л.с. и 9,9 л" stays one sentence). Every check of this module splits with it."""
    out, start = [], 0
    for m in _STOP_RE.finditer(line):
        if m.group(0)[0] == "." and _ABBREV_RE.search(line[start : m.start() + 1]):
            continue
        out.append(line[start : m.start() + 1])
        start = m.end()
    out.append(line[start:])
    return [x for x in out if x]


def numbers_in(obj: Any) -> set[float]:
    """Every value the facts may hold. An amount of euros written "€3.550" is 3 550, never 3.55 (our formatting
    groups thousands with a point), so a single 3-digit group next to a euro sign has its thousands reading only."""
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, default=str)
    out: set[float] = set()
    for m in _FACT_RE.finditer(text):
        token = m.group(1)
        money = _MONEY_AROUND.search(text[max(0, m.start() - 4) : m.start()]) or _MONEY_AROUND.search(
            text[m.end() : m.end() + 4])  # fmt: skip
        if money and _THOUSANDS_ONLY.fullmatch(token):
            out.add(float(_SEPARATOR.sub("", token)))
        else:
            out |= readings(token)
        if m.group(2):
            out |= readings(token, m.group(2))
    return out


def written(token: str, mult: str | None = None) -> set[tuple[Decimal, Decimal]]:
    """Every (value, step) a written number can mean: the step is the precision it is written with — its decimals
    ("9,8": 0.1), else, from 1000 up, its trailing zeros ("42 500": 100); an integer below 1000 is exact ("205",
    "10": 1, FR-033). A thousands multiplier scales both."""
    out: set[tuple[Decimal, Decimal]] = set()
    for value in readings(token):
        try:
            v = Decimal(repr(value)).normalize()
        except InvalidOperation:
            continue
        exponent = int(v.as_tuple().exponent)  # normalize(): 42500 → 4.25E+4 (step 100), 9.8 → step 0.1
        if exponent > 0 and abs(v) < 1000:  # FR-033: "10", "200" are exact; only amounts like "42 500" are rounded
            exponent = 0
        step = Decimal(1).scaleb(exponent) if v else Decimal(1)
        scale = Decimal(1000) if mult else Decimal(1)
        out.add((v * scale, step * scale))
    return out


def equal_at_precision(fact: float, value: Decimal, step: Decimal) -> bool:
    """The fact rounded (half up) to `step` equals the written `value` (FR-033: no blanket pass for small integers
    or years: "10 л/100 км" and "7 лет" must be in the facts)."""
    try:
        rounded = (Decimal(repr(fact)) / step).quantize(Decimal(1), ROUND_HALF_UP) * step
    except InvalidOperation:
        return False
    return rounded == value


def _token_ok(m: re.Match[str], allowed: set[float]) -> bool:
    vals = written(m.group(1), m.group(2))
    return not vals or any(equal_at_precision(a, v, step) for v, step in vals for a in allowed)


_LIST_MARK = re.compile(r"^\s*(?:\d{1,2}[.)]|[-*•])\s+")


def check_numbers(text: str, allowed: set[float], cars: int = 0) -> tuple[str, int]:
    """Drop sentences containing numbers not present in the allowed data. Returns (text, dropped). The count of
    cars compared (1..cars) and a list number at the start of a line are not figures."""
    allowed = allowed | {float(n) for n in range(1, cars + 1)}
    kept, dropped = [], 0
    for line in text.split("\n"):
        mark = _LIST_MARK.match(line)
        body = line[mark.end() :] if mark else line
        parts = sentences(body)
        good = [p for p in parts if all(_token_ok(m, allowed) for m in _CHECKED_RE.finditer(_METRIC_RE.sub(" ", p)))]
        dropped += len(parts) - len(good)
        if parts and not good:
            continue  # the whole line went: its list mark goes with it (no "2." left alone)
        kept.append(" ".join(([mark.group(0).strip()] if mark else []) + good))
    return "\n".join(kept).strip(), dropped


# --- report check (spec 004 FR-012; research R3) ---------------------------------------------------------------
# The text must not contradict the blocks: no "no data" where a block has data, no advantage below the
# threshold, no winner in a tie. Numbers are checked by `check_numbers` above.

# A word ending in "*" is a stem (any ending); every other entry matches as a whole word or phrase (FR-034).
_ABSENCE = ("no data", "not available", "insufficient data", "no information", "not found", "unknown",
            "нет данных", "данных нет", "недостаточно данных", "нет информации", "не найден*", "неизвестн*",
            "sin datos", "no hay datos", "datos insuficientes", "no disponible", "desconocid*")  # fmt: skip
_COMPARATIVE = ("better", "more", "bigger", "larger", "wins", "advantage*", "superior", "beats", "ahead",
                "лучше", "больше", "вместительн*", "выигрыва*", "преимуществ*", "превосход*", "опережа*",
                "mejor", "más", "mayor", "gana", "ventaja*", "supera")  # fmt: skip
_WINNER = ("best choice", "the winner", "wins overall", "we recommend", "i recommend", "clear choice", "pick the",
           "лучший выбор", "победител*", "рекомендую", "однозначно", "явный выбор", "выбирайте",
           "mejor opción", "ganador", "recomiendo", "elección clara")  # fmt: skip

# area / attribute → words that name it in the text (en, ru, es)
TOPIC_WORDS: dict[str, tuple[str, ...]] = {
    "tco": (
        "ownership cost*",
        "running cost*",
        "cost of ownership",
        "стоимост*",
        "владени*",
        "расходы на содерж*",
        "coste de propiedad",
        "costes",
        "mantener",
    ),  # fmt: skip
    "maintenance": ("maintenance", "service interval*", "servicing", "обслуживан*", "mantenimiento", "revisi*"),
    "price": ("price*", "цена", "цены", "цене", "стоимость покупки", "precio*"),
    "consumption": ("consumption", "fuel economy", "расход*", "consumo*"),
    "reliability": ("reliability", "надёжн*", "надежн*", "fiabilidad"),
    "boot_volume": ("boot", "trunk", "luggage", "багажник*", "maletero*"),
    "accel_0_100": ("acceleration", "0-100", "0–100", "разгон*", "aceleración"),
    "max_power": ("power", "мощност*", "potencia"),
    "curb_mass": ("weight", "масс*", "вес", "веса", "peso"),
    "ground_clearance": ("ground clearance", "клиренс*", "altura libre"),
    "official_price_es": ("price*", "цена", "цены", "цене", "стоит", "precio*"),
    "tco_per_year": ("ownership cost*", "running cost*", "стоимост*", "владени*", "coste*"),
    "tco_period": ("ownership cost*", "total cost*", "cost of ownership", "стоимост*", "владени*", "coste*"),
    "value_retention_5y": ("resale", "residual", "depreciation", "остаточн*", "потеря стоимости", "valor residual"),
    # spec 016 T304: every attribute of config/insights.yaml has its words (a test keeps the map complete)
    "reliability_score": ("reliability", "надёжн*", "надежн*", "fiabilidad"),
    "measured_0_100": ("acceleration", "0-100", "0–100", "разгон*", "aceleración"),
    "max_torque": ("torque", "крутящ*", "момент*", "par motor", "par máximo"),
    "top_speed": (
        "top speed",
        "maximum speed",
        "max speed",
        "максимальная скорость",
        "максимальной скорости",
        "максимальную скорость",
        "velocidad máxima",
        "velocidad punta",
    ),
    "rear_legroom": (
        "legroom",
        "rear seat*",
        "back seat*",
        "места сзади",
        "место для ног",
        "места для ног",
        "задн* ряд*",
        "espacio para las piernas",
        "plazas traseras",
        "asientos traseros",
    ),
    "euro_ncap_stars": ("euro ncap", "ncap", "crash test*", "безопасн*", "краш-тест*", "seguridad"),
}

# Chat 5821ac77: "Sorento … (saving €3,625 a year), pays back in about 3.5 years" while its 5-year total with
# depreciation was higher. A sentence that calls a car the saving / cheaper to own / paying back, about a car whose
# total over the period is higher, contradicts the totals.
_SAVING = ("saving*", "save", "saves", "cheaper", "less expensive", "pays back", "pay back", "pays for itself",
           "pays off", "more economical",
           "экономи*", "сэконом*", "дешевле", "выгодне*", "окупа*", "окупит*",
           "ahorr*", "más barato", "más barata", "más económic*", "amortiza*", "sale a cuenta")  # fmt: skip
# "cheaper to run (without depreciation)" is a labelled secondary figure, not a claim about the total
_WITHOUT_DEPRECIATION = ("without depreciation", "excluding depreciation", "before depreciation",
                         "без учёта потери стоимости", "без учета потери стоимости", "без учёта амортизации",
                         "без учета амортизации", "без потери стоимости", "sin depreciación", "sin contar la "
                         "depreciación", "sin la depreciación")  # fmt: skip
_NEGATION = ("not", "no", "never", "doesn't", "does not", "isn't", "won't", "не", "нет", "ни", "никогда",
             "nunca", "tampoco")  # fmt: skip
# "compared with the Prado, the Sorento …": a name right after these words is the reference, not the subject
_REFERENCE = re.compile(
    r"(?:\b(?:than|vs\.?|versus|against|with|over|compared to|for)|против|чем|сравнению с|"
    r"\bс|frente a|\bque|\bcon)\s+(?:the\s+|el\s+|la\s+)?$",
    re.I,
)


def _words(words: tuple[str, ...]) -> re.Pattern[str]:
    """FR-034: words match at word boundaries ("más" is not in "además", "more" not in "moreover"); a stem
    ("надёжн", "desconocid") matches the word it starts."""
    alts = []
    for w in sorted({x.strip() for x in words if x.strip()}, key=len, reverse=True):
        alts.append(re.escape(w[:-1]) + r"\w*" if w.endswith("*") else re.escape(w) + r"(?!\w)")
    return re.compile(r"(?<!\w)(?:" + "|".join(alts) + r")", re.I)


_ABSENCE_RE = _words(_ABSENCE)
_COMPARATIVE_RE = _words(_COMPARATIVE)
_WINNER_RE = _words(_WINNER)
_TOPIC_RE = {k: _words(v) for k, v in TOPIC_WORDS.items()}
_SAVING_RE = _words(_SAVING)
_WITHOUT_DEP_RE = _words(_WITHOUT_DEPRECIATION)
_NEGATION_RE = _words(_NEGATION)


@dataclass(frozen=True)
class Violation:
    rule: str  # absence | sub_threshold | tie_winner | saving_costlier
    sentence: str
    topic: str = ""


def _mentions(sentence: str, topic: str) -> bool:
    rx = _TOPIC_RE.get(topic)
    return rx is not None and rx.search(sentence) is not None


def _aliases(name: str) -> list[str]:
    """How the text may write a car: "Kia Sorento", "Sorento"; "Toyota Land Cruiser Prado", "Land Cruiser Prado",
    "Prado"."""
    words = name.split()
    out = [name, " ".join(words[1:])] if len(words) > 1 else [name]
    if len(words) > 2 and len(words[-1]) >= 3:
        out.append(words[-1])
    return [a for a in out if len(a) >= 3]


def _subject(sentence: str, names: tuple[str, ...]) -> str | None:
    """The car a sentence is about: the first one named that is not the reference of a comparison."""
    hits: list[tuple[int, str]] = []
    for n in names:
        for a in _aliases(n):
            for m in re.finditer(r"(?<!\w)" + re.escape(a) + r"(?!\w)", sentence, re.I):
                hits.append((m.start(), n))
    for pos, n in sorted(hits):
        if not _REFERENCE.search(sentence[:pos]):
            return n
    return None


def _names_a_car(sentence: str, names: tuple[str, ...]) -> bool:
    """The sentence names one of the cars, as the text may write it (`_aliases`)."""
    return any(re.search(r"(?<!\w)" + re.escape(a) + r"(?!\w)", sentence, re.I) for n in names if n
               for a in _aliases(n))  # fmt: skip


def saving_for_costlier(sentence: str, ci: CheckInput) -> bool:
    """A sentence that calls the car whose period total is higher a saving, cheaper or paying back (ru/en/es)."""
    if not ci.costlier or _WITHOUT_DEP_RE.search(sentence):
        return False
    claims = [m for m in _SAVING_RE.finditer(sentence)
              if not _NEGATION_RE.search(sentence[max(0, m.start() - 30):m.start()])]  # fmt: skip
    return bool(claims) and _subject(sentence, ci.car_names) in ci.costlier


def report_violations(text: str, ci: CheckInput) -> list[Violation]:
    out: list[Violation] = []
    for raw in (x for line in text.split("\n") for x in sentences(line)):
        s = raw.strip()
        if not s:
            continue
        if _ABSENCE_RE.search(s):
            topic = next((t for t in sorted(ci.has_data) if _mentions(s, t)), None)
            if topic:
                out.append(Violation("absence", s, topic))
                continue
        if _COMPARATIVE_RE.search(s):
            topic = next((t for t in sorted(ci.ties) if _mentions(s, t)), None)
            if topic:
                out.append(Violation("sub_threshold", s, topic))
                continue
        if saving_for_costlier(s, ci):
            out.append(Violation("saving_costlier", s, "tco_period"))
            continue
        if ci.tie and _WINNER_RE.search(s) and _names_a_car(s, ci.car_names):
            out.append(Violation("tie_winner", s))
    return out


def drop_sentences(text: str, bad: list[Violation]) -> str:
    """Last resort after one regeneration: remove the offending sentences."""
    gone = {v.sentence for v in bad}
    lines = []
    for line in text.split("\n"):
        parts = [p for p in sentences(line) if p.strip() not in gone]
        lines.append(" ".join(parts))
    return "\n".join(lines).strip()


def violations_prompt(bad: list[Violation]) -> str:
    """What to fix, for the one regeneration."""
    why = {
        "absence": "says data is missing although the report has it ({topic})",
        "sub_threshold": "presents a difference below the threshold as an advantage ({topic}: about the same)",
        "tie_winner": "names a winner although the verdict is a tie",
        "saving_costlier": "calls a car a saving or cheaper although its total cost over the ownership period, "
        "including depreciation, is higher; compare the totals including depreciation, and label running costs "
        "'without depreciation'",
    }
    lines = [f'- "{v.sentence}" — {why[v.rule].format(topic=v.topic)}' for v in bad]
    return "Rewrite the text. These sentences contradict the validated data:\n" + "\n".join(lines)
