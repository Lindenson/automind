"""What the person needs, for ranking the models of a line-up and the candidates (FR-008; spec 007 US7)."""

from __future__ import annotations

from dataclasses import dataclass, field

from automind.chat.domain.case.casefile import CaseFile


@dataclass(frozen=True)
class Fit:
    family: bool = False
    annual_km: int | None = None
    priorities: tuple[str, ...] = ()
    budget_eur: int | None = None
    reference_price_eur: int | None = None  # price of the other compared car (same segment ± 30 %)
    reasons_lang: str = "en"
    extra: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_case(cls, case: CaseFile) -> Fit:
        """The person's fit read from the case: family use, yearly distance, priorities, a total EUR budget, and the
        price of another compared car when the caller set it."""
        others = [int(p) for p in (getattr(c, "price_eur", None) for c in case.cars) if p]
        return cls(
            family=case.profile.family == "FAMILY" or "FAMILY" in case.usage or (case.needs.passengers or 0) >= 4,
            annual_km=case.profile.annual_km_max or case.annual_km,
            priorities=tuple(p.criterion for p in case.priorities),
            budget_eur=case.budget.max_eur if case.budget.kind == "TOTAL" and case.budget.currency == "EUR" else None,
            reference_price_eur=others[0] if others else None,
        )
