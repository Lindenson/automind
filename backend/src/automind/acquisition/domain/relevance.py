"""Relevance gate: is this page about the exact requested variant? (spec 003 FR-013, SC-004; research R7). Pure.

Runs before any value is extracted, so wrong-generation pages cost nothing and cannot leak values.
Signals, strongest first: another generation named in the title/URL; production years in the title/URL
outside the target generation; another engine (power ±5%) or body named in the title/URL; several engines
listed on the page; the target generation or one of its years named. Pages with no signal are UNCERTAIN
(the caller may ask the relevance role).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal

from automind.shared.evidence import sense, sibling_code

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
    transmission: str | None = None  # manual | automatic | dct | cvt | e-cvt | single (spec 004 FR-028)
    drive: str | None = None  # FWD | RWD | AWD
    names: tuple[str, ...] = ()  # other written names of the model, lower case ("理想l9", "lixiang l9"; aliases.yaml)


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
    # a Chinese page names the model in Chinese ("理想L9", "理想 L9"): every alias and local name, with and without
    # its spaces (chat 2026-11-06)
    names = {n for x in target.names for n in (x.lower(), x.lower().replace(" ", "")) if len(n) >= 3}
    return [make, *words, *sorted(names)]


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


# Whole words only (spec 009 FR-018): "manuales del propietario" is not a manual gearbox, "integrales" is not
# "integral". The title/URL has "-" and "_" turned into spaces before matching.
_AUTO_WORDS = ("dsg", "cvt", "e cvt", "ecvt", "6at", "8at", "steptronic", "tiptronic", "dct", "edc")
_AWD_WORDS = ("4x4", "awd", "4wd", "quattro", "xdrive", "4motion", "all wheel", "4matic", "integral",
              "tracción total", "traccion total", "allrad")  # fmt: skip
_TWO_WD_WORDS = ("fwd", "4x2", "2wd", "front wheel", "tracción delantera", "traccion delantera")
# Extra keywords layered by the infrastructure from accepted `rule_overrides` (spec 011 US5, `relevance.keywords.*`):
# `auto`, `awd`, `two_wd` add words to the lists above; `not_manual`, `not_auto` and `not_awd` list phrases that do
# not mean a manual gearbox ("manual del vehículo"), an automatic one or all-wheel drive (stop phrases, removed from
# the title/URL before the words are looked for). Empty unless a gated change was accepted.
KEYWORD_LISTS = ("auto", "awd", "two_wd", "not_manual", "not_auto", "not_awd")
KEYWORDS: dict[str, tuple[str, ...]] = {}


def configure_keywords(extra: dict[str, Sequence[str]]) -> None:
    KEYWORDS.clear()
    KEYWORDS.update({k: tuple(str(w).lower() for w in v) for k, v in extra.items() if k in KEYWORD_LISTS and v})


def _words(base: tuple[str, ...], name: str) -> tuple[str, ...]:
    return base + KEYWORDS.get(name, ())


def _without(t: str, stop_list: str) -> str:
    for w in KEYWORDS.get(stop_list, ()):
        t = re.sub(rf"(?<!\w){re.escape(w)}(?!\w)", " ", t)
    return t


def _manual(t: str) -> bool:
    return sense.says_manual(_without(t, "not_manual"))


def _automatic(t: str) -> bool:
    t = _without(t, "not_auto")
    return sense.says_automatic(t) or sense.has_word(t, _words(_AUTO_WORDS, "auto"))


def _gearbox_drive_signal(title_url: str, target: Target) -> Relevance | None:
    """A title or URL that names another gearbox or driven axle than the variant (e.g. a manual CX-5 page for
    the automatic): another variant (spec 004 FR-028). Only explicit whole words count (spec 009 FR-018)."""
    t = title_url.lower()
    gb = (target.transmission or "").lower()
    if gb == "manual" and _automatic(t) and not _manual(t):
        return Relevance("OTHER_VARIANT", "other gearbox: automatic (wanted manual)", "automatic")
    if gb and gb != "manual" and _manual(t) and not _automatic(t):
        return Relevance("OTHER_VARIANT", f"other gearbox: manual (wanted {gb})", "manual")
    dr = (target.drive or "").upper()
    awd = sense.has_word(_without(t, "not_awd"), _words(_AWD_WORDS, "awd"))
    two = sense.has_word(t, _words(_TWO_WD_WORDS, "two_wd"))
    if dr in ("FWD", "RWD") and awd and not two:
        return Relevance("OTHER_VARIANT", f"other drive: AWD (wanted {dr})", "AWD")
    if dr == "AWD" and two and not awd:
        return Relevance("OTHER_VARIANT", "other drive: 2WD (wanted AWD)", "2WD")
    return None


def _engine_body_signals(title_url: str, head: str, target: Target) -> Relevance | None:
    gd = _gearbox_drive_signal(title_url, target)
    if gd is not None:
        return gd
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


_BARE_YEAR = re.compile(r"\s*(19[89]\d|20[0-3]\d)\s*")


def resolve_generation(target: Target, generations: Sequence[GenerationInfo]) -> tuple[Target, list[GenerationInfo]]:
    """A generation recorded as a bare year ("2024") is mapped to the generation code and years containing that
    year, so pages of the same generation, its facelift included, stay relevant (spec 009 FR-019). Bare years
    are dropped from the known generations. Unknown year: no generation, and no single-year range to judge by."""
    gens = [g for g in generations if not _BARE_YEAR.fullmatch(g.code)]
    m = _BARE_YEAR.fullmatch(target.generation or "")
    if m is None:
        return target, gens
    year = int(m.group(1))
    hits = [g for g in gens if g.years_from is not None and g.contains(year)]
    if hits:  # on a boundary year (G30 to 2023, G60 from 2023) the newer generation
        g = max(hits, key=lambda h: h.years_from or 0)
        return replace(target, generation=g.code, years_from=g.years_from, years_to=g.years_to), gens
    if target.years_from == year and target.years_to in (None, year):
        return replace(target, generation=None, years_from=None, years_to=None), gens
    return replace(target, generation=None), gens


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()


def _names(word_list: Sequence[str], text: str) -> bool:
    return any(re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", text) for w in word_list)


def _make_words(make: str) -> list[str]:
    words = [w for w in re.split(r"[\s\-]+", _fold(make)) if len(w) >= 2]
    return words[:1]


def judge_brand(page: PageFacts, make: str, other_makes: Sequence[str] = ()) -> Relevance:
    """A page for a brand area (warranty, dealer network, results) is about the make, never one version: it is
    relevant when it names the make, whatever model or engine it shows. A page whose title or address names
    another make and not this one is about that make (a comparison text may name ours in passing)."""
    words = _make_words(make)
    text = _fold(f"{page.title}\n{page.url}\n{page.text[:HEAD_CHARS]}")
    if not words or not _names(words, text):
        return Relevance("NOT_ABOUT_CAR", f"the page does not name {make}")
    head = _fold(f"{page.title}\n{page.url}").replace("-", " ").replace("_", " ")
    if not _names(words, head):
        own = _fold(make)
        for other in other_makes:
            ow = _make_words(other)
            if _fold(other) != own and len(ow[0] if ow else "") >= 3 and _names(ow, head):
                return Relevance("NOT_ABOUT_CAR", f"the page is about {other}, not {make}", other)
    return Relevance("RELEVANT", f"names the make {make}")


# Brand-wide after-sales pages (spec 009 FR-020): maintenance plans, service, warranty.
SERVICE_WORDS = (
    "mantenimiento", "revision", "revisiones", "servicio", "servicios", "posventa", "postventa", "taller oficial",
    "garantia", "garantias", "maintenance", "service", "servicing", "warranty", "warranties", "aftersales",
    "after sales", "wartung", "inspektion", "garantie", "entretien", "manutenzione", "tagliando", "manutencao",
)  # fmt: skip


def is_service_page(page: PageFacts) -> bool:
    """The title or address speaks of maintenance, service or warranty."""
    head = _fold(f"{page.title}\n{page.url}").replace("-", " ").replace("_", " ").replace("/", " ")
    return _names(SERVICE_WORDS, head)


def judge_service(
    page: PageFacts, target: Target, generations: Sequence[GenerationInfo], other_makes: Sequence[str] = ()
) -> Relevance:
    """Maintenance and warranty data (spec 009 FR-020): the brand's service, maintenance and warranty pages name
    the make, not the model, and still apply to the car. Pages naming another generation, engine or gearbox stay
    rejected by the version rules; pages about another make are not about the car."""
    r = judge(page, target, generations)
    if r.verdict in ("RELEVANT", "OTHER_VARIANT", "MULTI_VARIANT") or not is_service_page(page):
        return r
    b = judge_brand(page, target.make, other_makes)
    if b.verdict != "RELEVANT":
        return b if r.verdict == "NOT_ABOUT_CAR" or b.other else r
    return Relevance("RELEVANT", f"brand-wide service page that names the make {target.make}")


def judge(page: PageFacts, target: Target, generations: Sequence[GenerationInfo]) -> Relevance:
    target, generations = resolve_generation(target, generations)
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
    if other_in_head is not None or (gen and sibling_code(gen, head)):
        which = other_in_head.label() if other_in_head else "another generation"
        return Relevance("MULTI_VARIANT", f"the page also mentions {which}; each value is checked", which)
    if target_in_title or (gen and _mentions(gen, head)) or in_range:
        return Relevance("RELEVANT", "names the requested generation, years or engine")
    want = power_ps_of(target.variant)
    if want and any(_same_power(p, want) for p in _powers(title_url)) and not siblings:
        return Relevance("RELEVANT", "names the requested engine")
    return Relevance("UNCERTAIN", "the page names neither the generation nor its years")
