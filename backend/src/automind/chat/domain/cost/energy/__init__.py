"""Chat · chat.domain.cost.energy: the energy cost of driving a car — pure (spec 006 US1, FR-001..FR-005, FR-013).

Owns: `model` — prices, the energy config from config/energy.yaml, usage context, car facts and estimate types;
  `estimate` — the cost per powertrain (combustion, BEV, plug-in with utility factor), mixes and price lines.
Flow: EnergyCar + UsageContext + EnergyConfig → estimate → EnergyEstimate (parts with inputs shown to the person).
Depends on: shared.vehicle. Must not depend on: sqlalchemy, the application, the dialog.
Public API: the names below (`from automind.chat.domain.cost import energy as en; en.estimate(...)`).
"""

from automind.chat.domain.cost.energy.estimate import (
    CS_PLAUSIBLE,
    UF_K,
    UF_MAX,
    electric_range,
    estimate,
    estimate_cs,
    factors,
    fuel_consumption,
    share,
    situation,
    utility_factor,
)
from automind.chat.domain.cost.energy.model import (
    CLTC_FACTOR,
    CS_MISSING,
    ELECTRIC,
    EV_CLTC_PLAUSIBLE,
    EV_MISSING,
    FUEL_MISSING,
    MAX_SHARE,
    PLUG_IN,
    EnergyCar,
    EnergyConfig,
    EnergyEstimate,
    EnergyPart,
    Price,
    Rates,
    UsageContext,
)

__all__ = [
    "CLTC_FACTOR",
    "CS_MISSING",
    "CS_PLAUSIBLE",
    "ELECTRIC",
    "EV_CLTC_PLAUSIBLE",
    "EV_MISSING",
    "EnergyCar",
    "EnergyConfig",
    "EnergyEstimate",
    "EnergyPart",
    "FUEL_MISSING",
    "MAX_SHARE",
    "PLUG_IN",
    "Price",
    "Rates",
    "UF_K",
    "UF_MAX",
    "UsageContext",
    "electric_range",
    "estimate",
    "estimate_cs",
    "factors",
    "fuel_consumption",
    "share",
    "situation",
    "utility_factor",
]
