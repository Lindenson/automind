"""The policy's configuration: the cost thresholds, the pass limit of a turn and the intake limits — one frozen
object, built once from the settings and `search.yaml intake`, validated when it is built."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from automind.chat.domain.intake import Limits


class PolicyConfig(BaseModel):
    """What the policy's rules compare against. No field has a default: a missing value is an error where the
    config is built, never a silent number.

    `max_passes`: policy passes in one turn before the limit pass (spec 007 FR-027); the limit pass is
    `max_passes + 1`. Raises `pydantic.ValidationError` when the hard cap is below the confirmation threshold."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    confirm_threshold_eur: float = Field(ge=0)
    hard_cap_eur: float = Field(ge=0)
    max_passes: int = Field(ge=1)
    intake: Limits

    @model_validator(mode="after")
    def _cap_not_below_threshold(self) -> PolicyConfig:
        if self.hard_cap_eur < self.confirm_threshold_eur:
            raise ValueError(f"hard cap €{self.hard_cap_eur} is below the confirmation threshold "
                             f"€{self.confirm_threshold_eur}")  # fmt: skip
        return self
