"""The engine of a car as a person names it: fuel and the engine facts of a request (spec 005 R4)."""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel, Field

Fuel = Literal["petrol", "diesel", "hybrid", "mhev", "phev", "bev", "lpg"]
FUELS: dict[str, Fuel] = {f: f for f in get_args(Fuel)}  # a fuel read from data: `FUELS.get(text)` (None: unknown)


class EngineHint(BaseModel):
    """The engine the user named (spec 005 R4): any subset of displacement, power, fuel and family."""

    displacement_l: float | None = Field(default=None, ge=0.6, le=8.0)
    power_hp: int | None = Field(default=None, ge=40, le=1000)
    power_kw: int | None = Field(default=None, ge=30, le=750)
    fuel: Fuel | None = None
    family: str | None = Field(default=None, max_length=16)  # TSI, TDI, DM-i, e:HEV …
    evidence: str = Field(default="", max_length=120)

    def empty(self) -> bool:
        return not any((self.displacement_l, self.power_hp, self.power_kw, self.fuel, self.family))

    def text(self) -> str:
        bits = [f"{self.displacement_l:.1f}" if self.displacement_l else "", self.family or "",
                f"{self.power_hp} CV" if self.power_hp else (f"{self.power_kw} kW" if self.power_kw else ""),
                self.fuel if self.fuel and not self.family else ""]  # fmt: skip
        return " ".join(b for b in bits if b)
