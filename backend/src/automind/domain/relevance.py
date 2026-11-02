"""Relevance gate: is this page about the exact requested variant? (spec 003 FR-013, SC-004; research R7). Pure.

Runs before any value is extracted, so wrong-generation pages cost nothing and cannot leak values.
Signals, strongest first: another generation named in the title/URL; production years in the title/URL
outside the target generation; another engine (power ±5%) or body named in the title/URL; several engines
listed on the page; the target generation or one of its years named. Pages with no signal are UNCERTAIN
(the caller may ask the relevance role).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from automind.domain.evidence import _sibling_code

Verdict = Literal["RELEVANT", "OTHER_VARIANT", "MULTI_VARIANT", "NOT_ABOUT_CAR", "UNCERTAIN"]

HEAD_CHARS = 3000
POWER_TOLERANCE = 0.05
KW_TO_PS = 1.35962
_POWER_RE = re.compile(r"(?<![\d.,])(\d{2,4})\s?(cv|ps|hp|bhp|ch|kw)\b", re.I)
_YEAR_RE = re.compile(r"(?<!\d)(19[89]\d|20[0-3]\d)(?!\d)")
WAGON_WORDS = ("touring", "estate", "wagon", "avant", "kombi", "sports tourer", "sportstourer", "ranchera",
               "familiar", "break", "sportbrake", "shooting brake", "variant", "sw ")  # fmt: skip
SALOON_TARGETS = ("SEDAN", "HATCHBACK")


@dataclass(frozen=True)
class GenerationInfo:
    code: str
    years_from: int | None
    years_to: int | None

    def label(self) -> str:
        if self.years_from is None:
            return self.code
        return f"{self.code} ({self.years_from}–{self.years_to or ''})"

    def contains(self, year: int) -> bool:
        lo = self.years_from if self.years_from is not None else 0
        hi = self.years_to if self.years_to is not None else 9999
        return lo <= year <= hi


@dataclass(frozen=True)
class Target:
    make: str
    model: str
    generation: str | None
    years_from: int | None
    years_to: int | None
    variant: str
    fuel: str | None = None
    body: str | None = None


@dataclass(frozen=True)
class PageFacts:
    url: str
    title: str
    text: str


@dataclass(frozen=True)
class Relevance:
    verdict: Verdict
    reason: str
    other: str | None = None


def power_ps_of(text: str) -> float | None:
    """The first power figure in a variant name or title, in PS (CV/PS/hp/ch ≈ PS; kW converted)."""
    m = _POWER_RE.search(text)
    if m is None:
        return None
    value, unit = float(m.group(1)), m.group(2).lower()
    return round(value * KW_TO_PS, 1) if unit == "kw" else value


def _powers(text: str) -> list[float]:
    out = []
    for m in _POWER_RE.finditer(text):
        v, unit = float(m.group(1)), m.group(2).lower()
        ps = v * KW_TO_PS if unit == "kw" else v
        if 40 <= ps <= 2000:
            out.append(ps)
    return out


def _mentions(code: str, text: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(code.lower())}(?![a-z0-9]|\.\d)", text) is not None


def _strip(code: str, text: str) -> str:
    return re.sub(rf"(?<![a-z0-9]){re.escape(code.lower())}(?![a-z0-9])", " ", text)


def _model_words(target: Target) -> list[str]:
    m = target.model.lower()
    # "CX-5", "CR-V", "RAV4", "3 Series": the whole name in its common spellings, then its longer words
    spellings = (
        {m, m.replace("-", " "), m.replace("-", ""), m.replace(" ", "")} if len(m.replace(" ", "")) >= 3 else set()
    )
    words = [w for w in re.split(r"[\s\-]+", m) if len(w) >= 3 and not w.isdigit()]
    words += sorted(spellings)
    make = re.split(r"[\s\-]+", target.make.lower())[0]
    return [make, *words]


def _same_power(a: float, b: float) -> bool:
    return abs(a - b) / b <= POWER_TOLERANCE


def _generation_signals(
    title_url: str, target: Target, siblings: Sequence[GenerationInfo]
) -> tuple[Relevance | None, bool, bool]:
    """(early verdict, target named in title/URL, a title/URL year inside the target generation)."""
    gen = (target.generation or "").lower()
    cleaned = title_url
    for g in siblings:
        cleaned = _strip(g.code, cleaned)
    target_in_title = bool(gen) and _mentions(gen, cleaned)
    for g in siblings:
        if _mentions(g.code, title_url) and not target_in_title:
            return Relevance("OTHER_VARIANT", f"other generation: {g.label()}", g.label()), False, False
    years = [int(y) for y in _YEAR_RE.findall(title_url)]
    tgt = GenerationInfo(target.generation or "", target.years_from, target.years_to)
    in_range = target.years_from is not None and any(tgt.contains(y) for y in years)
    if years and target.years_from is not None and not in_range and not target_in_title:
        for g in siblings:
            if any(g.contains(y) for y in years):
                return (
                    Relevance("OTHER_VARIANT", f"other generation: {g.label()} (year {years[0]})", g.label()),
                    False,
                    False,
                )
        return Relevance("OTHER_VARIANT", f"year {years[0]} is outside {tgt.label()}", str(years[0])), False, False
    return None, target_in_title, in_range


def _engine_body_signals(title_url: str, head: str, target: Target) -> Relevance | None:
    want = power_ps_of(target.variant)
    title_powers = _powers(title_url)
    if want and title_powers and not any(_same_power(p, want) for p in title_powers):
        return Relevance("OTHER_VARIANT", f"other engine: {round(title_powers[0])} CV (wanted {round(want)} CV)",
                         f"{round(title_powers[0])} CV")  # fmt: skip
    if (target.body or "").upper() in SALOON_TARGETS:
        word = next((w.strip() for w in WAGON_WORDS if w in f"{title_url} "), None)
        if word:
            return Relevance("OTHER_VARIANT", f"other body: {word} (wanted {(target.body or '').lower()})", word)
    head_powers = {round(p / 5) for p in _powers(head)}
    if len(head_powers) >= 3 and not (want and any(_same_power(p, want) for p in title_powers)):
        return Relevance("MULTI_VARIANT", f"the page lists {len(head_powers)} engines; only the matching one is used")
    return None


def judge(page: PageFacts, target: Target, generations: Sequence[GenerationInfo]) -> Relevance:
    title_url = f"{page.title}\n{page.url}".lower().replace("-", " ").replace("_", " ")
    head = page.text[:HEAD_CHARS].lower()
    everything = f"{title_url}\n{head}"
    codes = [g.code for g in generations] + ([target.generation] if target.generation else [])
    if not any(w in everything for w in _model_words(target)) and not any(_mentions(c, everything) for c in codes):
        return Relevance("NOT_ABOUT_CAR", f"the page does not name {target.make} {target.model}")
    gen = (target.generation or "").lower()
    siblings = [g for g in generations if g.code.lower() != gen]
    early, target_in_title, in_range = _generation_signals(title_url, target, siblings)
    if early is not None:
        return early
    other = _engine_body_signals(title_url, head, target)
    if other is not None:
        return other
    other_in_head = next((g for g in siblings if _mentions(g.code, head)), None)
    if other_in_head is not None or (gen and _sibling_code(gen, head)):
        which = other_in_head.label() if other_in_head else "another generation"
        return Relevance("MULTI_VARIANT", f"the page also mentions {which}; each value is checked", which)
    if target_in_title or (gen and _mentions(gen, head)) or in_range:
        return Relevance("RELEVANT", "names the requested generation, years or engine")
    want = power_ps_of(target.variant)
    if want and any(_same_power(p, want) for p in _powers(title_url)) and not siblings:
        return Relevance("RELEVANT", "names the requested engine")
    return Relevance("UNCERTAIN", "the page names neither the generation nor its years")
