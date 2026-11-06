"""S5 validate (spec 011 strangler, research R5): the checks every value passes before it is stored — the verbatim
excerpt, the unit layer, plausibility, the meaning ("sense") rules and the validator role. Moved from
`application/research.py` with the bodies unchanged; S4 moved the variant's fuel and gearbox first (relevance uses
them).
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from automind.application.ports import WebDoc
from automind.domain import evidence as ev
from automind.domain import plausibility, sense, sense_ev, specs
from automind.infrastructure import db

VERSION = "validate@2"  # 2: CLTC ranges and kWh/100 km never filed as WLTP (chat 2026-11-06)


def fuel_of(variant_name: str, powertrain: str | None) -> str | None:
    if (powertrain or "").upper() == "BEV":
        return "electric"
    n = f" {variant_name.lower()} "
    diesel = (" d ", "tdi", "dci", "cdi", "d-4d", "hdi", "crdi", "diesel", "jtd", "multijet", "tdci", "bluehdi",
              "skyactiv-d", "i-dtec", "ecoblue")  # fmt: skip
    if any(k in n for k in diesel) or re_diesel_suffix(n):
        return "diesel"
    return "petrol"


def re_diesel_suffix(n: str) -> bool:
    return re.search(r"\b\d{3}d\b|\b\d\.\dd\b|\b\d{3} d\b", n) is not None  # 520d, 2.0d, E 220 d


def _variant_gearbox(v: db.Variant) -> str | None:
    """The gearbox named in the variant name ("… 6AT", "… manual", "… e-CVT"), when the column is empty."""
    name = f" {v.variant_name} ".lower()
    if re.search(r"\b\d\s?(at|a/t)\b|automatic|automático|automatica", name):
        return "automatic"
    if re.search(r"\b\d\s?(mt|m/t)\b", name) or sense.says_manual(name):
        return "manual"
    return sense.gearbox_family(name)


CRITICAL = ("max_power", "max_torque", "curb_mass", "drivetrain", "claimed_0_100", "top_speed")


async def known_values(variant_id: str) -> dict[str, float]:
    async with db.sessionmaker()() as s:
        rows = await s.execute(
            select(db.SpecValue.attribute, db.SpecValue.value_num).where(
                db.SpecValue.variant_id == variant_id, db.SpecValue.available, db.SpecValue.value_num.is_not(None)
            )
        )
        return {a: float(n) for a, n in rows.all()}


def plausibility_ctx(v: db.Variant, known: dict[str, float]) -> plausibility.Context:
    return plausibility.Context(
        powertrain=v.powertrain, fuel=fuel_of(v.variant_name, v.powertrain), known=known,
        transmission=v.transmission or _variant_gearbox(v), drive=v.drive,
    )  # fmt: skip


MONEY_ATTRS = ("official_price_es",)


def check(
    c: Any,
    d: WebDoc,
    ctx: plausibility.Context | None = None,
    rules: dict[str, Any] | None = None,
    *,
    excerpt_checked: bool = False,
) -> tuple[str, float | None, str | None, str | None]:
    """(status, number, text, reject_rule): excerpt → unit → plausibility (FR-014) → sense (004 FR-027)."""
    if (
        not excerpt_checked
        and specs.RANGE_RE.search(c.raw_value) is None
        and not ev.validate_excerpt(c.excerpt, c.raw_value, d.text)
    ):
        return "REJECTED_UNSUPPORTED", None, None, None
    if c.attribute in MONEY_ATTRS and not (r := sense.money_marked(c.raw_value, c.excerpt)).ok:
        return "REJECTED_IMPLAUSIBLE", None, None, r.rule_id  # a number without a currency is not a price
    try:
        val = specs.normalize(specs.ATTRS[c.attribute], c.raw_value, c.unit, excerpt=c.excerpt, domain=d.url)
    except Exception:
        return "REJECTED_UNIT", None, None, None
    if ctx is not None and rules:
        p = plausibility.check(c.attribute, val, ctx, rules)
        if not p.ok:
            return "REJECTED_IMPLAUSIBLE", None, None, p.rule_id
    if ctx is not None:
        bad = _sense_after(c.attribute, val, ctx)
        if bad is not None:
            return bad
    return ("ACCEPTED", val, None, None) if isinstance(val, float) else ("ACCEPTED", None, str(val), None)


def _litres(raw: str) -> float | None:
    """ "611", "1.642" (Spanish thousands) or "611 l" as litres; None when there is no number."""
    m = re.search(r"\d[\d.,\u202f ]*", raw or "")
    if not m:
        return None
    digits = (
        re.sub(r"[.,\u202f ]", "", m.group(0)) if re.fullmatch(r"\d{1,2}[.,]\d{3}", m.group(0).strip()) else m.group(0)
    )
    try:
        return float(digits.strip().replace(",", "."))
    except ValueError:
        return None


def sense_before(
    c: Any, v: db.Variant, source_type: str | None, url: str = ""
) -> tuple[Any, tuple[str, None, None, str] | None]:
    """Re-file a claim under the attribute its value really is (WLTP / NEDC / real-world consumption); a boot
    volume with the seats folded, or of another body style, is not the boot volume."""
    if c.attribute == "boot_volume" and not (b := sense.boot_seats_up(c.raw_value, c.excerpt)).ok:
        return c, ("REJECTED_IMPLAUSIBLE", None, None, b.rule_id or "sense.boot")
    if c.attribute == "boot_volume" and not (b := sense.boot_fits_body(_litres(c.raw_value), v.body_class, url)).ok:
        return c, ("REJECTED_IMPLAUSIBLE", None, None, b.rule_id or "sense.boot")
    if (v.powertrain or "").upper() in sense_ev.PLUG_IN or c.attribute in _EV_CLAIMS:
        return _sense_ev_before(c, v, url)
    if c.attribute != "consumption":
        return c, None
    r = sense.classify_consumption(c.raw_value, c.excerpt, v.generation_years_from, source_type)
    if not r.ok:
        return c, ("REJECTED_IMPLAUSIBLE", None, None, r.rule_id or "sense.consumption")
    return _refile(c, r.attribute, r.value), None


_EV_CLAIMS = ("battery_kwh", "battery_gross_kwh", "charge_ac_kw", "charge_dc_peak_kw", "charge_dc_10_80_min",
              *sense_ev.EV_ATTRS, "consumption_cs", "consumption_weighted", "range_wltp", "range_cltc")  # fmt: skip


def _refile(c: Any, attribute: str | None, raw_value: Any) -> Any:
    update = {"attribute": attribute, "raw_value": raw_value}
    return c.model_copy(update=update) if hasattr(c, "model_copy") else dataclasses.replace(c, **update)


def _sense_ev_before(c: Any, v: db.Variant, url: str = "") -> tuple[Any, tuple[str, None, None, str] | None]:
    """Electric values (spec 006 R4): a plug-in's consumption by its words; gross vs usable; kWh vs kW; the test
    cycle of a range or kWh/100 km (a Chinese page's CLTC figure is never filed as WLTP, chat 2026-11-06)."""
    plug_in = (v.powertrain or "").upper() in sense_ev.PLUG_IN
    if plug_in and c.attribute in (*sense_ev.FUEL_ATTRS, *sense_ev.EV_ATTRS):
        r = sense_ev.plug_in_consumption(c.attribute, c.raw_value, c.unit, c.excerpt)
        if not r.ok:
            return c, ("REJECTED_IMPLAUSIBLE", None, None, r.rule_id or "sense.phev")
        c = _refile(c, r.attribute, r.value)
    elif c.attribute in ("consumption_cs", "consumption_weighted"):  # only plug-ins have these
        return c, ("REJECTED_IMPLAUSIBLE", None, None, "sense.phev.not_plug_in")
    if c.attribute in sense_ev.CYCLE_ATTRS:
        r = sense_ev.ev_cycle(c.attribute, c.raw_value, c.excerpt, url)
        if not r.ok:
            return c, ("REJECTED_IMPLAUSIBLE", None, None, r.rule_id or "sense.ev")
        c = _refile(c, r.attribute, c.raw_value)
    if c.attribute in ("battery_kwh", "battery_gross_kwh"):
        c = _refile(c, sense_ev.battery_kind(c.raw_value, c.excerpt), c.raw_value)
    r = sense_ev.check_claim(c.attribute, c.raw_value, c.unit, c.excerpt)
    if not r.ok:
        return c, ("REJECTED_IMPLAUSIBLE", None, None, r.rule_id or "sense.ev")
    return c, None


def _sense_after(attribute: str, val: Any, ctx: plausibility.Context) -> tuple[str, None, None, str] | None:
    """Meaning rules on a normalised value: gear counts of e-CVTs, another gearbox or drive than the variant."""
    if attribute == "gear_count" and isinstance(val, float):
        r = sense.gear_count(val, ctx.transmission, ctx.powertrain)
        if not r.ok:
            return "REJECTED_IMPLAUSIBLE", None, None, r.rule_id or "sense.gear_count"
    if attribute == "transmission" and sense.gearbox_conflict(ctx.transmission, str(val)):
        return "REJECTED_OTHER_VARIANT", None, None, "sense.transmission.other_gearbox"
    if attribute == "drivetrain" and sense.drive_conflict(ctx.drive, str(val)):
        return "REJECTED_OTHER_VARIANT", None, None, "sense.drivetrain.other_drive"
    if isinstance(val, float) and not (p := sense_ev.pair_check(attribute, val, ctx.known)).ok:
        return "REJECTED_IMPLAUSIBLE", None, None, p.rule_id or "sense.ev"
    return None


VALIDATOR_REJECTS = ("OTHER_VARIANT", "OTHER_MARKET", "OTHER_YEAR", "UNCLEAR")


@dataclass
class ReaderClaim:
    attribute: str
    raw_value: str
    unit: str | None
    excerpt: str
