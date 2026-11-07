"""Chat · chat.domain.understanding: facts read from the person's free text by code, without a model — the safety
net under the interpreter: new or used, region, yearly distance, home charging and electricity price, their own
consumption figures, and one text segment per car.

Owns: `condition`, `region`, `distance`, `charging`, `energy_figures`, `cars_in_text`, `amounts` (numbers a person
  wrote), `ownership` ("my" car, "to replace") — one concept each.
Depends on: chat.domain.case, shared.vehicle. Must not depend on: sqlalchemy, langgraph, fastapi, the application,
  the dialog.
Patterns and word tables are named module constants of the concept they belong to (T053).
Public API: the names below (`from automind.chat.domain import understanding; understanding.parse_distance(...)`).
"""

from automind.chat.domain.understanding.amounts import (
    amounts_in,
)
from automind.chat.domain.understanding.cars_in_text import (
    cars_in_text,
)
from automind.chat.domain.understanding.charging import (
    MAX_EUR_PER_KWH,
    any_match,
    charging_of,
    electricity_price_of,
)
from automind.chat.domain.understanding.condition import (
    condition_of,
)
from automind.chat.domain.understanding.distance import (
    parse_distance,
)
from automind.chat.domain.understanding.energy_figures import (
    APPLIES,
    BOUNDS,
    EnergyFigure,
    energy_figures_of,
    stated_for_cars,
)
from automind.chat.domain.understanding.ownership import (
    is_own_word,
    replaces_a_car,
    says_own,
)
from automind.chat.domain.understanding.region import (
    region_of,
)

__all__ = [
    "APPLIES",
    "BOUNDS",
    "EnergyFigure",
    "MAX_EUR_PER_KWH",
    "amounts_in",
    "any_match",
    "cars_in_text",
    "charging_of",
    "condition_of",
    "electricity_price_of",
    "energy_figures_of",
    "parse_distance",
    "is_own_word",
    "region_of",
    "replaces_a_car",
    "says_own",
    "stated_for_cars",
]
