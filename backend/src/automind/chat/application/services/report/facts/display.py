"""The rows of the specification table and how a selected value is written in them (units, yes/no, text)."""

from __future__ import annotations

from automind.acquisition.api.car import SpecValueRow
from automind.shared.vehicle import specs, units

TABLE_ROWS = [
    "engine",
    "max_power",
    "max_torque",
    "curb_mass",
    "drivetrain",
    "transmission",
    "displacement",
    "battery_kwh",
    "claimed_0_100",
    "top_speed",
    "consumption",
    "consumption_real",
    "consumption_nedc",
    # spec 006: electric facts (rows appear only when some car has a value)
    "battery_gross_kwh",
    "range_wltp",
    "range_real",
    "range_cltc",
    "consumption_ev",
    "consumption_ev_real",
    "consumption_ev_cltc",
    "consumption_cs",
    "consumption_weighted",
    "charge_ac_kw",
    "charge_dc_peak_kw",
    "charge_dc_10_80_min",
    "boot_volume",
    "seats",
    "official_price_es",
    "service_interval_km",
    "service_interval_months",
]


def display(key: str, sv: SpecValueRow | None) -> str | None:
    """A stored value as the spec table shows it (units of its attribute), None when there is no value."""
    if sv is None or not sv.available:
        return None
    if sv.value_text is not None:
        return sv.value_text
    x = sv.value_num
    if x is None:  # marked available with neither a number nor a text
        return None
    unit = specs.ATTRS[key].unit
    if key == "max_power":
        return units.kw_to_hp_display(x)
    if key == "official_price_es":
        return f"{x:,.0f} €".replace(",", ".")
    if key in ("consumption", "consumption_real", "consumption_nedc"):
        return f"{x:g}"
    if key in ("seats", "service_interval_months"):
        return f"{x:.0f}" + (" months" if key == "service_interval_months" else "")
    if key in ("curb_mass", "displacement", "service_interval_km", "boot_volume"):
        return f"{x:,.0f} {unit}".replace(",", ".")
    return f"{x:g} {unit}" if unit else f"{x:g}"
