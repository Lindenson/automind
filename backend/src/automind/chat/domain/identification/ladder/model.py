"""The identification ladder model (spec 008): levels and their order, a version and a generation of a model, what the
person wants (Wanted) and the versions left (Narrowed)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

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


AUTO_GEARBOXES = {"automatic", "dct", "cvt", "e-cvt", "single"}


POWERTRAIN = {"petrol": "ICE", "diesel": "ICE", "lpg": "ICE", "mhev": "MHEV", "hybrid": "HEV", "phev": "PHEV",
              "bev": "BEV"}  # fmt: skip


# sports lines sold under the model name: offered only when the user's words name the line (spec edge case)
_LINES = re.compile(r"(?<![\w-])(RS|vRS|GTI|GTD|GTE|AMG|JCW|NISMO|Type R|Cupra|N)(?![\w-])", re.I)


IMPLIED_FUEL = {"tdi": "diesel", "tsi": "petrol", "tfsi": "petrol", "crdi": "diesel", "hdi": "diesel",
                 "bluehdi": "diesel", "dci": "diesel", "d-4d": "diesel", "tce": "petrol", "puretech": "petrol",
                 "etsi": "mhev", "ecoboost": "petrol", "skyactiv-d": "diesel", "skyactiv-g": "petrol",
                 "t-gdi": "petrol", "crdi48": "diesel", "multijet": "diesel", "jtd": "diesel"}  # fmt: skip


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
                (line_of(self.engine) or "").lower(), (family_word(self) or "").lower())  # fmt: skip

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


def family_word(v: Version) -> str | None:
    """ "2.0 TDI" → "TDI"; a word that fits an EngineHint family (≤ 16 characters)."""
    word = re.sub(r"\b\d\.\d\b", " ", v.family).strip()
    word = " ".join(word.split())
    return word if word and len(word) <= 16 else None


def cv_label(kw: int) -> str:
    return f"{round(kw / 0.7355)} CV"
