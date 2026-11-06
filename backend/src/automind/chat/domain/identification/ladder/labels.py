"""Reconciling a car with its catalogue version and the labels shown to the person: status line, years, the registered-
version label."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from automind.chat.domain.identification.ladder.model import GEARBOX_LABEL, ORDER, Wanted, cv_label
from automind.shared.vehicle.identity import generation_matches


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


def status_line(name: str, generation: str | None, year: int | None, year_assumed: bool, w: Wanted,
                asking: str | None, words: Mapping[str, str]) -> str:  # fmt: skip
    """ "Audi A4 · B9 (2023) · diesel 2.0 TDI · power: ?" in the conversation language (`words`)."""
    parts = [name]
    when = f"~{year}" if year and year_assumed else (str(year) if year else "")
    if generation or when:
        parts.append(" ".join(x for x in (generation or "", f"({when})" if generation and when else when) if x))
    engine = " ".join(x for x in (words.get(w.fuel or "", w.fuel or "") if w.fuel else "",
                                   f"{w.displacement_l:.1f}" if w.displacement_l else "",
                                   w.family or "", cv_label(w.power_kw) if w.power_kw else "") if x)  # fmt: skip
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


_FUEL_CODE = {"phev": "PHEV", "hybrid": "HEV", "mhev": "MHEV", "bev": "EV"}


def years_text(years_from: int | None, years_to: int | None) -> str:
    """ "2021–2023", "2024–" (still on sale), "" when unknown."""
    if years_from is None:
        return ""
    if years_to is None:
        return f"{years_from}–"
    return f"{years_from}–{years_to}" if years_to != years_from else str(years_from)


def registered_label(fuel: str | None, engine_cc: int | None, engine_kw: int | None, power_is_max: bool,
                     years_from: int | None, years_to: int | None, words: Mapping[str, str]) -> str:  # fmt: skip
    """A version known from the registration datasets, in the user's language (`words`): "1.6 PHEV · engine
    118 kW · 2024–". A hybrid's kW is its combustion engine's, so it is named as the engine's and never shown as
    the car's power in CV; a combustion car's kW is its power ("2.2 diesel · 142 kW (193 CV) · 2021–")."""
    disp = f"{engine_cc / 1000:.1f}" if engine_cc else ""
    f = _FUEL_CODE.get(fuel or "") or words.get(fuel or "", fuel or "")
    if engine_kw and power_is_max:
        power = f"{engine_kw} kW ({cv_label(engine_kw)})"
    elif engine_kw:
        power = f"{words.get('engine', 'engine')} {engine_kw} kW"
    else:
        power = ""
    head = " ".join(x for x in (disp, f) if x)
    return " · ".join(x for x in (head, power, years_text(years_from, years_to)) if x)
