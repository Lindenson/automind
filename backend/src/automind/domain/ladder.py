"""Identification ladder (spec 008): a car is narrowed level by level over the versions really sold in its generation
— engine (fuel → family/displacement → power) → gearbox → driven wheels — never by guessing from one catalog row
("Octavia 2.0 diesel" is 116 CV or 150 CV, not "the 115 CV row we happen to have"). Pure and deterministic.

- `narrow`: the versions that fit what the user said and the year; what the user said that no version has is
  reported (`missing`) and not used for filtering, so the question shows what exists (FR-004).
- `next_step`: the coarsest level at which the fitting versions still differ (FR-006, FR-007).
- `decide`: the step to ask, or the settled version; "choose for me" and the ask limit settle levels by the base
  version rule (sources list the base version first), so no state can loop (FR-009…FR-011).
- `apply_option`: a tapped option is taken as the user's statement of that level.
- `reconcile`: a newer answer wins; levels the hub filled below a changed level are opened again (FR-005, FR-014).
- `status_line`: where the identification stands, on one line (FR-013).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from .identity import generation_matches

Level = Literal["FUEL", "ENGINE", "FAMILY", "POWER", "GEARBOX", "DRIVE"]
StepKind = Literal["DONE", "FUEL", "ENGINE", "FAMILY", "POWER", "GEARBOX", "DRIVE"]
Origin = Literal["STATED", "CHOSEN", "LIMIT"]
MAX_OPTIONS = 6
# the intake item (attempt counter) of each level: FAMILY and ENGINE are both the engine
ITEM: dict[str, str] = {"FUEL": "FUEL", "ENGINE": "ENGINE", "FAMILY": "ENGINE", "POWER": "POWER",
                        "GEARBOX": "GEARBOX", "DRIVE": "DRIVE"}  # fmt: skip
ITEMS = ("FUEL", "ENGINE", "POWER", "GEARBOX", "DRIVE")
# levels from the top, for corrections: a change opens again the levels below it (FR-014)
ORDER = ("YEAR", "GENERATION", "FUEL", "ENGINE", "POWER", "GEARBOX", "DRIVE")

GEARBOX_LABEL = {"manual": "manual", "automatic": "automatic", "dct": "DSG", "cvt": "CVT", "e-cvt": "e-CVT",
                 "single": "automatic"}  # fmt: skip
_AUTO = {"automatic", "dct", "cvt", "e-cvt", "single"}
POWERTRAIN = {"petrol": "ICE", "diesel": "ICE", "lpg": "ICE", "mhev": "MHEV", "hybrid": "HEV", "phev": "PHEV",
              "bev": "BEV"}  # fmt: skip
# sports lines sold under the model name: offered only when the user's words name the line (spec edge case)
_LINES = re.compile(r"(?<![\w-])(RS|vRS|GTI|GTD|GTE|AMG|JCW|NISMO|Type R|Cupra|N)(?![\w-])", re.I)
_IMPLIED_FUEL = {"tdi": "diesel", "tsi": "petrol", "tfsi": "petrol", "crdi": "diesel", "hdi": "diesel",
                 "bluehdi": "diesel", "dci": "diesel", "d-4d": "diesel", "tce": "petrol", "puretech": "petrol",
                 "etsi": "mhev", "ecoboost": "petrol", "skyactiv-d": "diesel", "skyactiv-g": "petrol",
                 "t-gdi": "petrol", "crdi48": "diesel", "multijet": "diesel", "jtd": "diesel"}  # fmt: skip


# --- the sourced list --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Version:
    """One version sold in a generation (sourced): the engine label as the source writes it ("2.0 TDI 150 CV")."""

    engine: str
    fuel: str | None = None
    engine_cc: int | None = None
    power_kw: int | None = None
    gearboxes: tuple[str, ...] = ()
    drives: tuple[str, ...] = ()
    years_from: int | None = None
    years_to: int | None = None
    source_url: str = ""
    excerpt: str = ""

    @property
    def cv(self) -> int | None:
        return round(self.power_kw / 0.7355) if self.power_kw else None

    @property
    def engine_key(self) -> tuple[Any, ...]:
        return (self.fuel, round((self.engine_cc or 0) / 100), self.power_kw and round(self.power_kw / 3),
                (line_of(self.engine) or "").lower(), (_family_word(self) or "").lower())  # fmt: skip

    @property
    def family(self) -> str:
        """The engine without its power: "2.0 TDI 150 CV" → "2.0 TDI"."""
        m = re.match(r"^(.*?)\s*\d{2,4}\s*(?:CV|PS|hp|HP|kW|cv|ps|CH|ch)\b", self.engine)
        base = (m.group(1) if m else self.engine).strip(" ,-")
        return base or self.engine


@dataclass
class Generation:
    make: str
    model: str
    generation: str
    years_from: int | None
    years_to: int | None
    body_class: str | None = None
    versions: list[Version] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)


def version_to_json(v: Version) -> dict[str, Any]:
    return {"engine": v.engine, "fuel": v.fuel, "engine_cc": v.engine_cc, "power_kw": v.power_kw,
            "gearboxes": list(v.gearboxes), "drives": list(v.drives), "years_from": v.years_from,
            "years_to": v.years_to, "source_url": v.source_url, "excerpt": v.excerpt}  # fmt: skip


def version_of_json(d: Mapping[str, Any]) -> Version:
    return Version(engine=str(d["engine"]), fuel=d.get("fuel"), engine_cc=d.get("engine_cc"),
                   power_kw=d.get("power_kw"), gearboxes=tuple(d.get("gearboxes") or ()),
                   drives=tuple(d.get("drives") or ()), years_from=d.get("years_from"), years_to=d.get("years_to"),
                   source_url=str(d.get("source_url") or ""), excerpt=str(d.get("excerpt") or ""))  # fmt: skip


def line_of(text: str | None) -> str | None:
    m = _LINES.search(text or "")
    return m.group(1).upper() if m else None


# --- what the user said ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Wanted:
    """What is known about the version (any subset): stated by the user, or taken by "choose for me"."""

    fuel: str | None = None
    displacement_l: float | None = None
    family: str | None = None  # TDI, TSI, e:HEV …
    power_kw: int | None = None
    engine: str | None = None  # the exact engine label of a tapped option
    gearbox: str | None = None  # manual | automatic | dct | …
    drive: str | None = None  # FWD | RWD | AWD
    year: int | None = None
    words: str = ""  # the user's words about the car (a sports line counts only when named)


def wanted_of(hint: Any, *, engine: str | None = None, gearbox: str | None = None, drive: str | None = None,
              year: int | None = None, words: str = "") -> Wanted:  # fmt: skip
    """From the case's EngineHint (any object with displacement_l, power_kw, power_hp, fuel, family)."""
    kw = None
    if hint is not None:
        kw = hint.power_kw or (round(hint.power_hp * 0.7355) if getattr(hint, "power_hp", None) else None)
    return Wanted(fuel=getattr(hint, "fuel", None), displacement_l=getattr(hint, "displacement_l", None),
                  family=getattr(hint, "family", None), power_kw=kw, engine=engine, gearbox=gearbox, drive=drive,
                  year=year, words=words)  # fmt: skip


@dataclass
class Narrowed:
    versions: list[Version]
    missing: list[str] = field(default_factory=list)  # what the user said that no version (of this year) has


def _base_fuel(v: Version) -> str | None:
    """The liquid fuel of a mild hybrid from its engine family ("1.5 TSI m-HEV" → petrol, "2.0 TDI MHEV" → diesel)."""
    low = v.engine.lower()
    hit = next((f for f in _IMPLIED_FUEL if re.search(rf"(?<![\w-]){re.escape(f)}(?![\w-])", low)), None)
    if hit and _IMPLIED_FUEL[hit] in ("petrol", "diesel"):
        return _IMPLIED_FUEL[hit]
    return "diesel" if re.search(r"di[eé]sel|\bd\b|\bdci\b", low) else None


def _fuel_ok(want: str, have: str | None, v: Version | None = None) -> bool:
    if have is None or want == have:
        return True
    if have == "mhev":  # a mild hybrid is still a petrol or a diesel: which one, from its engine family
        base = _base_fuel(v) if v is not None else None
        return want == "hybrid" or (want in ("petrol", "diesel") and base in (want, None))
    return False


def _family_ok(family: str, v: Version) -> bool:
    fam, low = family.lower(), v.engine.lower()
    if re.search(rf"(?<![\w-]){re.escape(fam)}(?![\w-])", low):  # "TSI" is not "eTSI"
        return True
    # a family word the source does not write ("TDI" for "2.0 diésel 150 CV"): the fuel decides, unless the
    # source names another family
    implied = _IMPLIED_FUEL.get(fam)
    named = any(re.search(rf"(?<![\w-]){re.escape(f)}(?![\w-])", low) for f in _IMPLIED_FUEL)
    return implied is not None and not named and v.fuel is not None and _fuel_ok(implied, v.fuel, v)


def _gearbox_ok(v: Version, wanted: str) -> bool:
    if not v.gearboxes:
        return True
    if wanted == "automatic":
        return any(g in _AUTO for g in v.gearboxes)
    return wanted in v.gearboxes


def _cv(kw: int) -> str:
    return f"{round(kw / 0.7355)} CV"


def narrow(versions: Sequence[Version], w: Wanted) -> Narrowed:
    """Filter from the top level down; a statement that no version has is reported and skipped."""
    pool = [v for v in versions if w.year is None or v.years_from is None
            or generation_matches(w.year, v.years_from, v.years_to, tolerance=1)] or list(versions)  # fmt: skip
    named = line_of(w.words)
    lined = [v for v in pool if (line_of(v.engine) or None) == named] if named else []
    if named and lined:
        pool = lined
    elif not named:  # "Octavia" is not the Octavia RS: the line is offered only when named
        pool = [v for v in pool if line_of(v.engine) is None] or pool
    missing: list[str] = []
    if w.engine:
        exact = [v for v in pool if v.engine.lower() == w.engine.lower()]
        if exact:
            pool = exact
    checks: list[tuple[str | None, Any]] = [
        (w.fuel, lambda v: _fuel_ok(w.fuel or "", v.fuel, v)),
        (f"{w.displacement_l:.1f}" if w.displacement_l else None,
         lambda v: v.engine_cc is None or abs(v.engine_cc / 1000 - (w.displacement_l or 0)) <= 0.05),
        (w.family, lambda v: _family_ok(w.family or "", v)),
        (_cv(w.power_kw) if w.power_kw else None,
         lambda v: v.power_kw is None or abs(v.power_kw - (w.power_kw or 0)) <= 3),
        (GEARBOX_LABEL.get(w.gearbox or "", w.gearbox), lambda v: _gearbox_ok(v, w.gearbox or "")),
        (w.drive, lambda v: not v.drives or w.drive in v.drives),
    ]  # fmt: skip
    for said, ok in checks:
        if not said:
            continue
        fit = [v for v in pool if ok(v)]
        if fit:
            pool = fit
        else:
            missing.append(said)
    return Narrowed(pool, missing)


def without(w: Wanted, missing: Sequence[str]) -> Wanted:
    """The statements that exist: what `narrow` reported missing is not shown as a settled level (FR-013)."""
    gone = set(missing)
    if not gone:
        return w
    return replace(
        w,
        fuel=None if w.fuel in gone else w.fuel,
        displacement_l=None if w.displacement_l and f"{w.displacement_l:.1f}" in gone else w.displacement_l,
        family=None if w.family in gone else w.family,
        power_kw=None if w.power_kw and _cv(w.power_kw) in gone else w.power_kw,
        gearbox=None if w.gearbox and GEARBOX_LABEL.get(w.gearbox, w.gearbox) in gone else w.gearbox,
        drive=None if w.drive in gone else w.drive,
    )


# --- the next question -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Option:
    level: Level
    label: str
    fuel: str | None = None
    engine_cc: int | None = None
    family: str | None = None
    power_kw: int | None = None
    engine: str | None = None
    gearbox: str | None = None
    drive: str | None = None


@dataclass
class Step:
    kind: StepKind
    options: list[Option] = field(default_factory=list)
    version: Version | None = None
    gearbox: str | None = None
    drive: str | None = None


def _family_word(v: Version) -> str | None:
    """ "2.0 TDI" → "TDI"; a word that fits an EngineHint family (≤ 16 characters)."""
    word = re.sub(r"\b\d\.\d\b", " ", v.family).strip()
    word = " ".join(word.split())
    return word if word and len(word) <= 16 else None


def _boxes(v: Version, wanted: str | None) -> list[str]:
    boxes = list(dict.fromkeys(v.gearboxes))
    if wanted and wanted in boxes:
        return [wanted]
    if wanted == "automatic":  # any automatic kind the version has (DSG, CVT …): the user's word covers them
        return [g for g in boxes if g in _AUTO][:1]
    return [g for g in boxes if g == wanted] if wanted else boxes


def _engine_option(level: Level, v: Version) -> Option:
    return Option(level, v.engine, fuel=v.fuel, engine_cc=v.engine_cc, family=_family_word(v), power_kw=v.power_kw,
                  engine=v.engine)  # fmt: skip


def _engine_step(many: list[Version], w: Wanted) -> Step:
    """Several engines: their fuel first and then their family when there are too many to list (FR-006)."""
    fuels = list(dict.fromkeys(v.fuel for v in many))
    families: dict[str, Version] = {}
    for v in many:
        families.setdefault(f"{v.fuel}|{v.family.lower()}", v)
    if len(many) > MAX_OPTIONS and len(fuels) > 1 and not w.fuel:  # many engines: first the fuel …
        return Step("FUEL", [Option("FUEL", f or "?", fuel=f) for f in fuels if f][:MAX_OPTIONS])
    if len(many) > MAX_OPTIONS and len(families) > 1 and not (w.family and w.displacement_l):  # … the family
        fams = list(families.values())[:MAX_OPTIONS]
        return Step("FAMILY", [Option("FAMILY", v.family, fuel=v.fuel, engine_cc=v.engine_cc,
                                      family=_family_word(v)) for v in fams])  # fmt: skip
    level: Level = "POWER" if len(families) == 1 else "ENGINE"
    return Step(level, [_engine_option(level, v) for v in many[:MAX_OPTIONS]])


def next_step(found: Narrowed, w: Wanted) -> Step:
    """The coarsest level at which the versions still differ (or DONE with the one version)."""
    vs = found.versions
    if not vs:
        return Step("DONE")
    engines: dict[tuple[Any, ...], Version] = {}
    for v in vs:
        engines.setdefault(v.engine_key, v)
    if len(engines) > 1:
        return _engine_step(list(engines.values()), w)
    v = next(iter(engines.values()))
    same = [x for x in vs if x.engine_key == v.engine_key]
    boxes = list(dict.fromkeys(g for x in same for g in _boxes(x, w.gearbox)))
    if w.gearbox:  # the user's gearbox is settled: never asked again as two automatic kinds
        boxes = boxes[:1]
    labels: dict[str, str] = {}
    for g in boxes:
        labels.setdefault(GEARBOX_LABEL.get(g, g), g)
    if len(labels) > 1:
        return Step("GEARBOX", [Option("GEARBOX", lab, engine=v.engine, gearbox=g) for lab, g in labels.items()])
    box = boxes[0] if boxes else w.gearbox
    drives = list(dict.fromkeys(d for x in same for d in x.drives if not w.drive or d == w.drive))
    if len(drives) > 1:
        return Step("DRIVE", [Option("DRIVE", d, engine=v.engine, gearbox=box, drive=d) for d in drives])
    return Step("DONE", version=v, gearbox=box, drive=drives[0] if drives else w.drive)


def apply_option(w: Wanted, o: Option) -> Wanted:
    """The option is taken as the user's statement of its level (and of the levels above it that it carries)."""
    if o.level == "GEARBOX":
        return replace(w, gearbox=o.gearbox, engine=o.engine or w.engine)
    if o.level == "DRIVE":
        return replace(w, drive=o.drive, gearbox=o.gearbox or w.gearbox, engine=o.engine or w.engine)
    disp = round(o.engine_cc / 1000, 1) if o.engine_cc else None
    if o.level == "FUEL":
        return replace(w, fuel=o.fuel)
    if o.level == "FAMILY":
        return replace(w, fuel=o.fuel or w.fuel, displacement_l=disp or w.displacement_l, family=o.family or w.family)
    return replace(w, fuel=o.fuel or w.fuel, displacement_l=disp or w.displacement_l, family=o.family or w.family,
                   power_kw=o.power_kw or w.power_kw, engine=o.engine)  # fmt: skip


@dataclass(frozen=True)
class Auto:
    """A level the hub settled: "choose for me" (CHOSEN) or after the ask limit (LIMIT)."""

    level: Level
    label: str
    origin: Origin


@dataclass
class Decision:
    step: Step  # DONE (with the version) or the question to ask
    wanted: Wanted  # what is known now, with the levels the hub settled
    missing: list[str] = field(default_factory=list)
    auto: list[Auto] = field(default_factory=list)

    @property
    def done(self) -> bool:
        return self.step.kind == "DONE" and self.step.version is not None


def decide(versions: Sequence[Version], w: Wanted, asks: Mapping[str, int], *, limit: int = 2,
           chosen: bool = False) -> Decision:  # fmt: skip
    """The question to ask, or the version. A level asked `limit` times, or any level after "choose for me", is
    settled by its first option (sources list the base version first) and the ladder goes on down."""
    found = narrow(versions, w)
    missing = list(found.missing)
    auto: list[Auto] = []
    step = next_step(found, w)
    seen: set[tuple[Any, ...]] = set()
    for _ in range(len(ORDER) + MAX_OPTIONS):  # bounded: every pass settles one level
        if step.kind == "DONE" or not step.options:
            break
        origin: Origin | None = "CHOSEN" if chosen else ("LIMIT" if asks.get(ITEM[step.kind], 0) >= limit else None)
        if origin is None:
            break
        sig = (step.kind, tuple(o.label for o in step.options))
        first = step.options[0]
        auto.append(Auto(first.level, first.label, origin))
        if sig in seen:  # the option did not narrow (a family the label cannot name): the base version of the rest
            w = apply_option(w, _engine_option("ENGINE", narrow(versions, w).versions[0]))
        else:
            seen.add(sig)
            w = apply_option(w, first)
        step = next_step(narrow(versions, w), w)
    return Decision(step, w, missing, auto)


# --- corrections (FR-005, FR-014) --------------------------------------------------------------------------------


def levels_of(year: int | None, year_assumed: bool, generation: str | None, w: Wanted) -> dict[str, str]:
    """The value of each level as text (a snapshot to compare with the next turn)."""
    engine = "|".join(str(x) for x in (w.displacement_l or "", (w.family or "").lower(), (w.engine or "").lower()))
    vals = {"YEAR": "" if year is None or year_assumed else str(year), "GENERATION": (generation or "").lower(),
            "FUEL": w.fuel or "", "ENGINE": engine.strip("|"), "POWER": str(w.power_kw or ""),
            "GEARBOX": w.gearbox or "", "DRIVE": w.drive or ""}  # fmt: skip
    return {k: v for k, v in vals.items() if v}


@dataclass
class Reconciled:
    clear: list[str] = field(default_factory=list)  # levels the hub had filled, opened again
    changed: list[str] = field(default_factory=list)  # levels the user changed (their own values now)
    drop: str | None = None  # "YEAR" or "GENERATION": the older of two conflicting answers
    note: dict[str, Any] | None = None  # level_replaced: {old, new, span}


def reconcile(before: Mapping[str, str], now: Mapping[str, str], origin: Mapping[str, str],
              spans: Mapping[str, tuple[int | None, int | None]]) -> Reconciled:  # fmt: skip
    """The highest level the user changed: the levels below it that the hub filled are opened again; a year and a
    generation that cannot both be true keep the newer one."""
    out = Reconciled()
    changed = [lvl for lvl in ORDER if before.get(lvl) != now.get(lvl) and now.get(lvl)]
    if not changed:
        return out
    out.changed = changed
    top = ORDER.index(changed[0])
    out.clear = [lvl for lvl in ORDER[top + 1 :] if origin.get(lvl) in ("CHOSEN", "LIMIT") and lvl not in changed]
    year, gen = now.get("YEAR"), now.get("GENERATION")
    span = spans.get(gen or "") if gen else None
    if year and gen and span and span[0] is not None and not generation_matches(int(year), span[0], span[1], 1):
        years = f"{span[0]}–{span[1] or ''}".rstrip("–") if span[1] else f"{span[0]}–"
        if "GENERATION" in changed and "YEAR" not in changed:
            out.drop, out.note = "YEAR", {"old": year, "new": gen.upper(), "span": years}
        elif "YEAR" in changed and "GENERATION" not in changed:
            out.drop, out.note = "GENERATION", {"old": gen.upper(), "new": year, "span": years}
    return out


# --- where it stands (FR-013) ------------------------------------------------------------------------------------


def status_line(name: str, generation: str | None, year: int | None, year_assumed: bool, w: Wanted,
                asking: str | None, words: Mapping[str, str]) -> str:  # fmt: skip
    """ "Audi A4 · B9 (2023) · diesel 2.0 TDI · power: ?" in the conversation language (`words`)."""
    parts = [name]
    when = f"~{year}" if year and year_assumed else (str(year) if year else "")
    if generation or when:
        parts.append(" ".join(x for x in (generation or "", f"({when})" if generation and when else when) if x))
    engine = " ".join(x for x in (words.get(w.fuel or "", w.fuel or "") if w.fuel else "",
                                   f"{w.displacement_l:.1f}" if w.displacement_l else "",
                                   w.family or "", _cv(w.power_kw) if w.power_kw else "") if x)  # fmt: skip
    if w.engine and not w.power_kw:
        engine = w.engine
    if engine:
        parts.append(engine)
    if w.gearbox:
        parts.append(words.get(w.gearbox, GEARBOX_LABEL.get(w.gearbox, w.gearbox)))
    if w.drive:
        parts.append(w.drive)
    if asking:
        parts.append(f"{words.get(asking.lower(), asking.lower())}: ?")
    return " · ".join(p for p in parts if p)
