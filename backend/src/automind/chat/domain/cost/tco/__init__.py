"""Chat · chat.domain.cost.tco: the ownership cost (TCO) engine — pure and deterministic (FR-033..FR-035; research R9).

Owns: `model` — rates, schedules, the car facts and the estimate types; `items` — one function per cost item
  (maintenance, energy, tyres, road tax, big tickets, depreciation, repair reserve); `compute` — the total over the
  period, the cost curve, payback and like-for-like.
Flow: TcoCar + TcoRates → items.* (one TcoItem each) → compute → TcoEstimate.
Depends on: chat.domain.cost.energy, shared.vehicle. Must not depend on: sqlalchemy, the application, the dialog.
Note: the repair-reserve age bands are repeated in code (items._band) and in config/rates.yaml (age_bands).
Public API: the names below (`from automind.chat.domain.cost import tco; tco.compute(...)`).
"""

from automind.chat.domain.cost.tco.compute import (
    MAX_PAYBACK_YEARS,
    compute,
    cost_curve,
    depreciation_known,
    like_for_like,
    payback_years,
)
from automind.chat.domain.cost.tco.items import (
    MIN_INTERVAL_KM,
    big_tickets_item,
    depreciation_item,
    energy_car,
    energy_consumption,
    energy_estimate,
    energy_item,
    energy_rates,
    maintenance_item,
    reserve_item,
    road_tax_item,
    tyres_item,
    value_share,
)
from automind.chat.domain.cost.tco.model import (
    CLASSES,
    RULES_VERSION,
    Basis,
    BigTicket,
    Kind,
    MaintenanceSched,
    TcoCar,
    TcoEstimate,
    TcoItem,
    TcoRates,
)

__all__ = [
    "Basis",
    "BigTicket",
    "CLASSES",
    "Kind",
    "MAX_PAYBACK_YEARS",
    "MIN_INTERVAL_KM",
    "MaintenanceSched",
    "RULES_VERSION",
    "TcoCar",
    "TcoEstimate",
    "TcoItem",
    "TcoRates",
    "big_tickets_item",
    "compute",
    "cost_curve",
    "depreciation_item",
    "depreciation_known",
    "energy_car",
    "energy_consumption",
    "energy_estimate",
    "energy_item",
    "energy_rates",
    "like_for_like",
    "maintenance_item",
    "payback_years",
    "reserve_item",
    "road_tax_item",
    "tyres_item",
    "value_share",
]
