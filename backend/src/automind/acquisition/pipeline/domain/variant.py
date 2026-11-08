"""The car a research job is about, as the stages read it: `VariantFacts` (any object with these attributes — the
store's `CarVariant`, or a stored row the replay and the gates read) and `CarVariant`, the frozen record."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class VariantFacts(Protocol):
    """What the pipeline reads of a variant (identity, gearbox, drive, home market)."""

    @property
    def id(self) -> str:
        """The variant's id."""
        ...

    @property
    def make(self) -> str:
        """The canonical make."""
        ...

    @property
    def model(self) -> str:
        """The model."""
        ...

    @property
    def generation(self) -> str | None:
        """The generation code, if known."""
        ...

    @property
    def variant_name(self) -> str:
        """The version's name (engine, power, trim words)."""
        ...

    @property
    def powertrain(self) -> str:
        """ICE | HEV | MHEV | PHEV | BEV | …"""
        ...

    @property
    def body_class(self) -> str | None:
        """The body style, if known."""
        ...

    @property
    def generation_years_from(self) -> int | None:
        """The generation's first year, if known."""
        ...

    @property
    def generation_years_to(self) -> int | None:
        """The generation's last year (None: still sold)."""
        ...

    @property
    def transmission(self) -> str | None:
        """The gearbox family, if known."""
        ...

    @property
    def drive(self) -> str | None:
        """FWD | RWD | AWD, if known."""
        ...

    @property
    def market(self) -> str:
        """Where the variant is sold ("ES" by default)."""
        ...

    @property
    def label(self) -> str:
        """ "Make Model Generation Variant"."""
        ...


@dataclass(frozen=True)
class CarVariant:
    """A stored variant as the pipeline reads it."""

    id: str
    make: str
    model: str
    generation: str | None
    variant_name: str
    powertrain: str
    body_class: str | None
    generation_years_from: int | None
    generation_years_to: int | None
    transmission: str | None
    drive: str | None
    market: str

    @property
    def label(self) -> str:
        """ "Make Model Generation Variant", as the stored variant labels itself."""
        gen = f" {self.generation}" if self.generation else ""
        return f"{self.make} {self.model}{gen} {self.variant_name}".replace("  ", " ").strip()
