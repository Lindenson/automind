"""The policy's config is built once at startup from the settings and `search.yaml intake` (spec 015 T210); an
invalid one stops the app from starting."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from automind.chat.infrastructure.adapters import policy_config
from automind.shared.infrastructure.config.loader import search_config
from automind.shared.infrastructure.config.settings import Settings


def test_the_config_comes_from_the_settings_and_the_intake_limits() -> None:
    s = Settings(cost_confirm_threshold_eur=0.3, cost_hard_cap_eur=1.0, policy_max_passes=8)
    cfg = policy_config(s, {"intake": {"max_attempts_per_item": 3}})
    assert (cfg.confirm_threshold_eur, cfg.hard_cap_eur) == (Decimal("0.3"), Decimal("1.0"))
    assert cfg.max_passes == 8 and cfg.intake.max_attempts_per_item == 3
    assert policy_config(s, search_config()).intake.max_attempts_per_item >= 1


def test_a_hard_cap_below_the_threshold_stops_the_start() -> None:
    with pytest.raises(ValidationError, match="below the confirmation threshold"):
        policy_config(Settings(cost_confirm_threshold_eur=0.5, cost_hard_cap_eur=0.4), {})


def test_no_pass_at_all_stops_the_start() -> None:
    with pytest.raises(ValidationError):
        policy_config(Settings(policy_max_passes=0), {})
