"""The next question of the ladder (one level at a time, at most MAX_OPTIONS options), applying the option picked, and
deciding when the car is identified."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from automind.chat.domain.identification.ladder.model import (
    AUTO_GEARBOXES,
    GEARBOX_LABEL,
    ITEM,
    MAX_OPTIONS,
    ORDER,
    Level,
    Narrowed,
    Origin,
    StepKind,
    Version,
    Wanted,
    family_word,
)
from automind.chat.domain.identification.ladder.narrow import narrow


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


def _boxes(v: Version, wanted: str | None) -> list[str]:
    boxes = list(dict.fromkeys(v.gearboxes))
    if wanted and wanted in boxes:
        return [wanted]
    if wanted == "automatic":  # any automatic kind the version has (DSG, CVT …): the user's word covers them
        return [g for g in boxes if g in AUTO_GEARBOXES][:1]
    return [g for g in boxes if g == wanted] if wanted else boxes


def _engine_option(level: Level, v: Version) -> Option:
    return Option(level, v.engine, fuel=v.fuel, engine_cc=v.engine_cc, family=family_word(v), power_kw=v.power_kw,
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
                                      family=family_word(v)) for v in fams])  # fmt: skip
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


def levels_of(year: int | None, year_assumed: bool, generation: str | None, w: Wanted) -> dict[str, str]:
    """The value of each level as text (a snapshot to compare with the next turn)."""
    engine = "|".join(str(x) for x in (w.displacement_l or "", (w.family or "").lower(), (w.engine or "").lower()))
    vals = {"YEAR": "" if year is None or year_assumed else str(year), "GENERATION": (generation or "").lower(),
            "FUEL": w.fuel or "", "ENGINE": engine.strip("|"), "POWER": str(w.power_kw or ""),
            "GEARBOX": w.gearbox or "", "DRIVE": w.drive or ""}  # fmt: skip
    return {k: v for k, v in vals.items() if v}
