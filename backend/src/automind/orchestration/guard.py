"""Number guard (FR-031): every number in AI-written text must exist in validated or computed data."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")
# Numbers inside model codes (J250, Mk8, F30, i30, D-4D) are names, not figures: not checked.
_CHECKED_RE = re.compile(r"(?<![A-Za-z])(?<![A-Za-z]-)(?<![\d.,])\d+(?:[.,]\d+)?")
ALWAYS_OK = {0.0, 100.0, 200.0, 400.0, 62.0, 60.0}  # 0-100 km/h, 0-200, 400 m, 0-62 mph


def _to_float(n: str) -> float:
    return float(n.replace(",", "."))


def numbers_in(obj: Any) -> set[float]:
    text = json.dumps(obj, ensure_ascii=False, default=str)
    return {_to_float(n) for n in _NUM_RE.findall(text)}


def _ok(x: float, allowed: set[float]) -> bool:
    if x in ALWAYS_OK or (x.is_integer() and (x <= 12 or 1950 <= x <= 2035)):
        return True
    return any(abs(x - a) <= max(0.051, 0.005 * abs(a)) for a in allowed)


def check_numbers(text: str, allowed: set[float]) -> tuple[str, int]:
    """Drop sentences containing numbers not present in the allowed data. Returns (text, dropped)."""
    kept, dropped = [], 0
    for line in text.split("\n"):
        good = []
        for p in re.split(r"(?<=[.!?])\s+", line):
            if all(_ok(_to_float(n), allowed) for n in _CHECKED_RE.findall(p)):
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

_ABSENCE = ("no data", "not available", "insufficient data", "no information", "not found", "unknown",
            "нет данных", "данных нет", "недостаточно данных", "нет информации", "не найден", "неизвестн",
            "sin datos", "no hay datos", "datos insuficientes", "no disponible", "desconocid")  # fmt: skip
_COMPARATIVE = ("better", "more", "bigger", "larger", "wins", "advantage", "superior", "beats", "ahead",
                "лучше", "больше", "вместительн", "выигрыва", "преимуществ", "превосход", "опережа",
                "mejor", "más", "mayor", "gana", "ventaja", "supera")  # fmt: skip
_WINNER = ("best choice", "the winner", "wins overall", "we recommend", "i recommend", "clear choice", "pick the",
           "лучший выбор", "победител", "рекомендую", "однозначно", "явный выбор", "выбирайте",
           "mejor opción", "ganador", "recomiendo", "elección clara")  # fmt: skip

# area / attribute → words that name it in the text (en, ru, es)
TOPIC_WORDS: dict[str, tuple[str, ...]] = {
    "tco": (
        "ownership cost",
        "running cost",
        "cost of ownership",
        "стоимост",
        "владени",
        "расходы на содерж",
        "coste de propiedad",
        "costes",
        "mantener",
    ),
    "maintenance": ("maintenance", "service interval", "servicing", "обслуживан", "то ", "mantenimiento", "revisi"),
    "price": ("price", "цена", "стоимость покупки", "precio"),
    "consumption": ("consumption", "fuel economy", "расход", "consumo"),
    "reliability": ("reliability", "надёжн", "надежн", "fiabilidad"),
    "boot_volume": ("boot", "trunk", "luggage", "багажник", "maletero"),
    "accel_0_100": ("acceleration", "0-100", "0–100", "разгон", "aceleración"),
    "max_power": ("power", "мощност", "potencia"),
    "curb_mass": ("weight", "масс", "вес ", "peso"),
    "ground_clearance": ("ground clearance", "клиренс", "altura libre"),
    "official_price_es": ("price", "цена", "стоит", "precio"),
    "tco_per_year": ("ownership cost", "running cost", "стоимост", "владени", "coste"),
    "value_retention_5y": ("resale", "residual", "depreciation", "остаточн", "потеря стоимости", "valor residual"),
}

_SENT = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass(frozen=True)
class Violation:
    rule: str  # absence | sub_threshold | tie_winner
    sentence: str
    topic: str = ""


@dataclass(frozen=True)
class CheckInput:
    has_data: frozenset[str]  # topics with data in the blocks (TOPIC_WORDS keys)
    ties: frozenset[str]  # insight attributes whose cars are about the same
    tie: bool  # the verdict is a tie
    car_names: tuple[str, ...]  # short names of the cars as the text may write them


def _mentions(sentence: str, topic: str) -> bool:
    s = f" {sentence.lower()} "
    return any(w in s for w in TOPIC_WORDS.get(topic, ()))


def report_violations(text: str, ci: CheckInput) -> list[Violation]:
    out: list[Violation] = []
    for raw in _SENT.split(text):
        s = raw.strip()
        if not s:
            continue
        low = s.lower()
        if any(w in low for w in _ABSENCE):
            topic = next((t for t in sorted(ci.has_data) if _mentions(s, t)), None)
            if topic:
                out.append(Violation("absence", s, topic))
                continue
        if any(w in low for w in _COMPARATIVE):
            topic = next((t for t in sorted(ci.ties) if _mentions(s, t)), None)
            if topic:
                out.append(Violation("sub_threshold", s, topic))
                continue
        if ci.tie and any(w in low for w in _WINNER) and any(n.lower() in low for n in ci.car_names if n):
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
    }
    lines = [f'- "{v.sentence}" — {why[v.rule].format(topic=v.topic)}' for v in bad]
    return "Rewrite the text. These sentences contradict the validated data:\n" + "\n".join(lines)
