"""IntakeConfig (identification/contracts.py): config/search.yaml `intake` read once, typed, with the code's defaults
for keys the section does not set, and a clear error for a value that is not a number."""

from __future__ import annotations

from dataclasses import replace

import pytest

from automind.chat.application.services.identification.contracts import (
    CATALOG_STALE_YEARS,
    MAX_ATTEMPTS_PER_ITEM,
    IntakeConfig,
)
from automind.chat.dialog.prompts import load_all
from automind.chat.domain.identification import used
from automind.delivery.bootstrap import reference


def test_reads_the_section_and_defaults_the_rest() -> None:
    ref = reference(load_all())
    cfg = IntakeConfig.of(replace(ref, search={"intake": {"max_attempts_per_item": "3", "km_per_year_used": 9000}}))
    assert cfg == IntakeConfig(max_attempts_per_item=3, km_per_year_used=9000, default_used_age=used.DEFAULT_USED_AGE,
                               catalog_stale_years=CATALOG_STALE_YEARS)  # fmt: skip
    empty = IntakeConfig.of(replace(ref, search={}))
    assert empty.max_attempts_per_item == MAX_ATTEMPTS_PER_ITEM and empty.km_per_year_used == used.KM_PER_YEAR_USED


def test_the_shipped_config_is_read() -> None:
    cfg = IntakeConfig.of(reference(load_all()))
    assert (cfg.max_attempts_per_item, cfg.catalog_stale_years) == (2, 0)


def test_a_value_that_is_not_a_number_is_named() -> None:
    ref = reference(load_all())
    with pytest.raises(TypeError, match="intake: a number expected"):
        IntakeConfig.of(replace(ref, search={"intake": {"max_attempts_per_item": [2]}}))
