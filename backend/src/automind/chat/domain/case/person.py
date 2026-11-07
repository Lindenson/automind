"""The person behind a case: profile, budget, running-cost limit, needs, rates, priorities and their own energy
figures."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from automind.chat.domain.case.enums import BudgetIntent, Climate, CriterionKey, HomeCharging, Strength


class Profile(BaseModel):
    age: int | None = Field(default=None, ge=14, le=100)
    experience: str | None = None
    # spec 004 FR-017: inferred only from the user's words; `evidence` keeps those words per field
    family: Literal["SINGLE", "COUPLE", "FAMILY"] | None = None
    age_band: Literal["UNDER_25", "25_40", "40_60", "OVER_60"] | None = None
    driving_style: Literal["CALM", "MIXED", "SPORTY"] | None = None
    # spec 005 R11: where the car is driven and how far (a range when the user gives one)
    region: str | None = Field(default=None, max_length=60)
    region_code: str | None = None
    climate: Climate | None = None
    annual_km_min: int | None = Field(default=None, ge=1000, le=200000)
    annual_km_max: int | None = Field(default=None, ge=1000, le=200000)
    # spec 006 R5: where the user can charge (UNKNOWN is assumed YES and said so in the report)
    home_charging: HomeCharging = "UNKNOWN"
    evidence: dict[str, str] = Field(default_factory=dict)


class Budget(BaseModel):
    max_eur: int | None = Field(default=None, ge=0)  # the amount as stated (see currency and kind)
    note: str | None = None
    intent: BudgetIntent = "UNKNOWN"  # spec 003: a new car, a used one, or either
    currency: Literal["EUR", "GBP", "USD"] = "EUR"
    kind: Literal["TOTAL", "MONTHLY"] = "TOTAL"


class RunningLimit(BaseModel):
    """Most the user wants to spend on running the car (spec 003 FR-018)."""

    amount_eur: float = Field(gt=0)
    period: Literal["MONTH", "YEAR"] = "MONTH"

    @property
    def per_month(self) -> float:
        return self.amount_eur if self.period == "MONTH" else self.amount_eur / 12


class Needs(BaseModel):
    """Usage needs that a car must meet (spec 003 FR-018). Mountains come from `usage`."""

    passengers: int | None = Field(default=None, ge=1, le=9)
    luggage: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    towing_kg: int | None = Field(default=None, ge=100, le=4000)
    daily_km: int | None = Field(default=None, ge=1, le=2000)


class Rates(BaseModel):
    fuel_eur_per_l: float | None = Field(default=None, gt=0)
    diesel_eur_per_l: float | None = Field(default=None, gt=0)
    electricity_eur_per_kwh: float | None = Field(default=None, gt=0)  # legacy: read as the home price
    labour_eur_per_h: float | None = Field(default=None, gt=0)
    # spec 006 R7: the user's own electricity prices (0 = free charging at work) and a night tariff
    home_electricity_eur_per_kwh: float | None = Field(default=None, ge=0, le=1.5)
    public_ac_eur_per_kwh: float | None = Field(default=None, ge=0, le=1.5)
    public_dc_eur_per_kwh: float | None = Field(default=None, ge=0, le=1.5)
    night_tariff: bool | None = None


class Priority(BaseModel):
    criterion: CriterionKey
    strength: Strength
    source: Literal["USER", "PERSONA"] = "USER"


class StatedEnergy(BaseModel):
    """A consumption figure the user gave for one of the cars ("в гибридном режиме 5,5 л"): it replaces the sourced
    or estimated value in the energy cost and is labelled as the user's (spec 006 follow-up). FUEL: l/100 km in real
    use (combustion and non-plug hybrids); CS: a plug-in with an empty battery; KWH: kWh/100 km as the car shows it;
    RANGE: real electric km on a full charge. No car_key: the one car the figure can apply to (decided at compute)."""

    kind: Literal["FUEL", "CS", "KWH", "RANGE"]
    value: float = Field(gt=0, le=1000)
    words: str = Field(default="", max_length=120)
    car_key: str | None = None
