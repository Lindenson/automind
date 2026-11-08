"""The registry's settings (`config/registry.yaml`), typed once: what the rules read, with the defaults the code has
always used when a key is missing (a test or an older file may give a partial mapping). Pure."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from automind.shared.contracts.json import JsonObject

OTHER = "OTHER"  # the source type whose prior stands in for an unknown one
NO_PRIOR = (1.0, 1.0)


@dataclass(frozen=True)
class Promote:
    """candidate → active: enough attempts, accuracy lower bound, yield and accuracy signals (spec 011 FR-012)."""

    min_attempts: float = 8.0
    min_acc_lb: float = 0.6
    min_yield: float = 0.2
    min_signals: float = 5.0


@dataclass(frozen=True)
class Degrade:
    """active → degraded: a low bound or yield over enough attempts, or no accepted value in the last N."""

    min_attempts: float = 10.0
    max_acc_lb: float = 0.45
    max_yield: float = 0.05
    zero_in_last: int = 10


@dataclass(frozen=True)
class Recover:
    """degraded → active: the bound and the yield are back above these."""

    min_acc_lb: float = 0.55
    min_yield: float = 0.15


@dataclass(frozen=True)
class Lifecycle:
    """The thresholds of the capability lifecycle (domain/lifecycle.py)."""

    promote: Promote = field(default_factory=Promote)
    degrade: Degrade = field(default_factory=Degrade)
    recover: Recover = field(default_factory=Recover)
    retire_after_days: float = 21.0
    retired_retry_days: float = 30.0


@dataclass(frozen=True)
class ScoreConfig:
    """What the score of a capability depends on besides its counts (domain/score.py)."""

    priors: Mapping[str, tuple[float, float]] = field(default_factory=dict)
    wilson_z: float = 1.96
    cost_lambda: float = 2.0

    def prior(self, source_type: str | None) -> tuple[float, float]:
        """Pseudo-counts (right, wrong) of a source type; `OTHER`'s for an unknown type, else (1, 1)."""
        return self.priors.get(source_type or OTHER) or self.priors.get(OTHER) or NO_PRIOR


@dataclass(frozen=True)
class RegistryConfig:
    """The registry's settings as its rules and services read them."""

    autonomy: bool = False
    half_life_days: float = 90.0
    weights: Mapping[str, float] = field(default_factory=dict)
    score: ScoreConfig = field(default_factory=ScoreConfig)
    lifecycle: Lifecycle = field(default_factory=Lifecycle)
    candidate_slots: int = 1
    explore_eur_per_day: float = 0.10
    explore_max_candidates: int = 1
    recheck_active_days: int = 90
    recheck_blocked_days: int = 180
    discovery_eur_per_day: float = 0.2
    families: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def weight_of(self, kind: str) -> float:
        """The weight of a truth signal of this kind (1 when not configured)."""
        return float(self.weights.get(kind, 1.0))

    @classmethod
    def from_mapping(cls, raw: JsonObject) -> RegistryConfig:
        """Read the YAML mapping; a missing key keeps its default."""
        explore, recheck = _section(raw, "explore"), _section(raw, "recheck_days")
        return cls(
            autonomy=bool(raw.get("autonomy", False)),
            half_life_days=float(raw.get("half_life_days", 90)),
            weights={str(k): float(v) for k, v in _section(raw, "weights").items()},
            score=ScoreConfig(
                _priors(_section(raw, "priors")), float(raw.get("wilson_z", 1.96)), float(raw.get("cost_lambda", 2.0))
            ),  # fmt: skip
            lifecycle=_lifecycle(_section(raw, "lifecycle")),
            candidate_slots=int(raw.get("candidate_slots", 1)),
            explore_eur_per_day=float(explore.get("eur_per_day", 0.10)),
            explore_max_candidates=int(explore.get("max_candidates_per_job", 1)),
            recheck_active_days=int(recheck.get("active", 90)),
            recheck_blocked_days=int(recheck.get("blocked", 180)),
            discovery_eur_per_day=float(_section(raw, "discovery").get("eur_per_day", 0.2)),
            families={str(k): tuple(str(m) for m in v or []) for k, v in _section(raw, "families").items()},
        )


def _section(raw: JsonObject, key: str) -> JsonObject:
    value = raw.get(key)
    return dict(value) if isinstance(value, Mapping) else {}


def _priors(raw: JsonObject) -> dict[str, tuple[float, float]]:
    return {str(k): (float(v[0]), float(v[1])) for k, v in raw.items() if v}


def _lifecycle(raw: JsonObject) -> Lifecycle:
    pro, deg, rec = _section(raw, "promote"), _section(raw, "degrade"), _section(raw, "recover")
    return Lifecycle(
        Promote(
            float(pro.get("min_attempts", 8)),
            float(pro.get("min_acc_lb", 0.6)),
            float(pro.get("min_yield", 0.2)),
            float(pro.get("min_signals", 5)),
        ),  # fmt: skip
        Degrade(
            float(deg.get("min_attempts", 10)),
            float(deg.get("max_acc_lb", 0.45)),
            float(deg.get("max_yield", 0.05)),
            int(deg.get("zero_in_last", 10)),
        ),  # fmt: skip
        Recover(float(rec.get("min_acc_lb", 0.55)), float(rec.get("min_yield", 0.15))),
        float(raw.get("retire_after_days", 21)),
        float(raw.get("retired_retry_days", 30)),
    )
