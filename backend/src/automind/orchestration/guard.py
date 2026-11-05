"""Number guard (FR-031): every number in AI-written text must exist in validated or computed data."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

# A number as written in any of our languages: "25 000", "25.000", "25,000", "1.234,5", "6,58", "20k", "20 тыс".
_NUM = r"\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)*"
_MULT = r"(?:\s?([kк](?![a-zа-яё])|тыс\.?|mil\b|thousand))?"
_NUM_RE = re.compile(rf"({_NUM}){_MULT}", re.I)
# Numbers inside model codes (J250, Mk8, F30, i30, D-4D) are names, not figures: not checked.
_CHECKED_RE = re.compile(rf"(?<![A-Za-z])(?<![A-Za-z]-)(?<![\d.,])({_NUM}){_MULT}", re.I)
ALWAYS_OK = {0.0, 100.0, 200.0, 400.0, 62.0, 60.0}  # 0-100 km/h, 0-200, 400 m, 0-62 mph


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


def numbers_in(obj: Any) -> set[float]:
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, default=str)
    out: set[float] = set()
    for m in _NUM_RE.finditer(text):
        out |= readings(m.group(1))
        if m.group(2):
            out |= readings(m.group(1), m.group(2))
    return out


def _ok(x: float, allowed: set[float]) -> bool:
    # FR-033: no blanket pass for small integers and years: "10 л/100 км" and "7 лет" must be in the facts
    if x in ALWAYS_OK:
        return True
    return any(abs(x - a) <= max(0.051, 0.005 * abs(a)) for a in allowed)


def _token_ok(m: re.Match[str], allowed: set[float]) -> bool:
    vals = readings(m.group(1), m.group(2))
    return not vals or any(_ok(x, allowed) for x in vals)


_LIST_MARK = re.compile(r"^\s*(?:\d{1,2}[.)]|[-*•])\s+")


def check_numbers(text: str, allowed: set[float], cars: int = 0) -> tuple[str, int]:
    """Drop sentences containing numbers not present in the allowed data. Returns (text, dropped). The count of
    cars compared (1..cars) and a list number at the start of a line are not figures."""
    allowed = allowed | {float(n) for n in range(1, cars + 1)}
    kept, dropped = [], 0
    for line in text.split("\n"):
        good = []
        mark = _LIST_MARK.match(line)
        if mark:
            good.append(mark.group(0).strip())
            line = line[mark.end() :]
        for p in re.split(r"(?<=[.!?])\s+", line):
            if all(_token_ok(m, allowed) for m in _CHECKED_RE.finditer(p)):
                good.append(p)
            else:
                dropped += 1
        kept.append(" ".join(good))
    return "\n".join(kept).strip(), dropped


def removal_notice(dropped: int) -> dict[str, str]:
    return {
        "type": "notice",
        "level": "info",
        "text": f"{dropped} sentence(s) removed by the number check (numbers not found in validated data).",
    }


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

_SENT = re.compile(r"(?<=[.!?])\s+|\n+")


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


@dataclass(frozen=True)
class CheckInput:
    has_data: frozenset[str]  # topics with data in the blocks (TOPIC_WORDS keys)
    ties: frozenset[str]  # insight attributes whose cars are about the same
    tie: bool  # the verdict is a tie
    car_names: tuple[str, ...]  # short names of the cars as the text may write them
    costlier: tuple[str, ...] = ()  # short names of the cars whose total over the period (incl. depreciation) is higher


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


def saving_for_costlier(sentence: str, ci: CheckInput) -> bool:
    """A sentence that calls the car whose period total is higher a saving, cheaper or paying back (ru/en/es)."""
    if not ci.costlier or _WITHOUT_DEP_RE.search(sentence):
        return False
    claims = [m for m in _SAVING_RE.finditer(sentence)
              if not _NEGATION_RE.search(sentence[max(0, m.start() - 30):m.start()])]  # fmt: skip
    return bool(claims) and _subject(sentence, ci.car_names) in ci.costlier


def report_violations(text: str, ci: CheckInput) -> list[Violation]:
    out: list[Violation] = []
    for raw in _SENT.split(text):
        s = raw.strip()
        if not s:
            continue
        low = s.lower()
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
        if ci.tie and _WINNER_RE.search(s) and any(n.lower() in low for n in ci.car_names if n):
            out.append(Violation("tie_winner", s))
    return out


def drop_sentences(text: str, bad: list[Violation]) -> str:
    """Last resort after one regeneration: remove the offending sentences."""
    gone = {v.sentence for v in bad}
    lines = []
    for line in text.split("\n"):
        parts = [p for p in re.split(r"(?<=[.!?])\s+", line) if p.strip() not in gone]
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
