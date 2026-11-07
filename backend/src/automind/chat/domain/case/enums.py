"""The closed vocabularies of a case: criteria keys, personas, conditions, usages, resolutions, question and intake
kinds."""

from __future__ import annotations

from typing import Literal, get_args

CRITERION_KEYS = (
    "reliability",
    "ownership_cost",
    "purchase_price",
    "practicality",
    "comfort",
    "performance",
    "driving_fun",
    "traction_all_weather",
    "offroad_mountain",
    "efficiency",
    "safety",
    "status",
    "engineering",
)


CriterionKey = Literal[
    "reliability",
    "ownership_cost",
    "purchase_price",
    "practicality",
    "comfort",
    "performance",
    "driving_fun",
    "traction_all_weather",
    "offroad_mountain",
    "efficiency",
    "safety",
    "status",
    "engineering",
]


Persona = Literal["EXPERT", "PERFORMANCE", "BUYER", "UNKNOWN"]


PersonaSource = Literal["INFERRED", "ASKED", "USER_EDIT"]


# spec 007 FR-001: how each profile field is known. STATED: the user said it (chat or panel); INFERRED: read from
# the user's words with evidence; ASSUMED: a default. A weaker basis never overwrites a stronger one.
ProfileBasis = Literal["STATED", "INFERRED", "ASSUMED"]


BASIS_RANK: dict[str, int] = {"ASSUMED": 0, "INFERRED": 1, "STATED": 2}


PROFILE_FIELDS = ("persona", "ownership_years", "condition", "annual_km", "budget", "monthly_limit", "family",
                  "driving_style", "age_band", "region", "usage")  # fmt: skip


Usage = Literal["CITY", "MOTORWAY", "MOUNTAINS", "OFFROAD", "TRACK", "FAMILY"]


Depth = Literal["QUICK", "STANDARD", "DEEP"]


Condition = Literal["NEW", "USED", "UNKNOWN"]


Gearbox = Literal["manual", "automatic", "dct", "cvt", "e-cvt", "single"]
GEARBOXES: dict[str, Gearbox] = {g: g for g in get_args(Gearbox)}  # a gearbox read from data: `.get(text)`


Drive = Literal["FWD", "RWD", "AWD"]
DRIVES: dict[str, Drive] = {d: d for d in get_args(Drive)}  # driven wheels read from data: `.get(text)`


Resolution = Literal["UNRESOLVED", "PROPOSED", "CONFIRMED", "AUTO_OK", "UNKNOWN_MODEL"]


Strength = Literal["LOW", "MEDIUM", "HIGH"]


QuestionKind = Literal[
    "TOO_MANY_CARS", "CAR_IDENTITY", "USED_AGE", "TRIM", "PERSONA", "BUDGET_INTENT", "UNKNOWN_MODEL", "GEARBOX",
    "KM_PER_YEAR", "FAMILY_SIZE", "CONDITION", "ENGINE", "MAKE_LINEUP", "PROPOSE", "REMOVE_OR_CHOOSE",
    "OWNERSHIP_YEARS", "CONFIRM_PROFILE", "HOME_CHARGING", "FUEL", "POWER", "DRIVE",
]  # fmt: skip


# spec 005: what an intake step is about (R6)
IntakeItem = Literal["MAKE", "MODEL", "ENGINE", "GEARBOX", "YEAR", "CONDITION", "MILEAGE", "TRIM", "CHOICE", "FUEL",
                     "POWER", "DRIVE"]  # fmt: skip
INTAKE_ITEMS: dict[str, IntakeItem] = {i: i for i in get_args(IntakeItem)}  # an item named in data: `.get(text)`


Climate = Literal["HOT", "MILD", "COLD", "MOUNTAIN"]


BudgetIntent = Literal["NEW", "USED", "ANY", "UNKNOWN"]


MAX_CARS = 3


IdentifyKind = Literal["IDENTIFIED", "CHOICES", "NEED", "NOT_FOUND"]
