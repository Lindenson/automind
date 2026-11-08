"""ValueSelection over a fake value store: the gearbox from agreeing claims, then the values selected in one store
call; a store failure propagates (the caller's job fails, nothing half-written)."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from automind.acquisition.pipeline.application.ports import PipelineStoreUnavailable, SelectValues
from automind.acquisition.pipeline.application.selection import ValueSelection
from automind.acquisition.pipeline.domain import selection
from automind.acquisition.pipeline.domain.selection import ScheduleItem
from automind.shared import evidence as ev


class FakeValues:
    def __init__(self, transmissions: list[str], claims: list[ev.ClaimIn], schedule: Sequence[ScheduleItem] = (),
                 down: bool = False) -> None:  # fmt: skip
        self.transmissions, self.claims, self.schedule, self.down = transmissions, claims, list(schedule), down
        self.gearbox: str | None = None
        self.selected: list[selection.SelectedValue] = []

    async def known_values(self, variant_id: str) -> dict[str, float]:
        return {}

    async def accepted_transmissions(self, variant_id: str) -> list[str]:
        return self.transmissions

    async def set_gearbox(self, variant_id: str, family: str) -> None:
        self.gearbox = family

    async def replace_selected(self, variant_id: str, select: SelectValues) -> None:
        if self.down:
            raise PipelineStoreUnavailable("replace_selected: OperationalError")
        self.selected = select(self.claims, self.schedule)


def _claim(i: int, attr: str, value: float | str, domain: str) -> ev.ClaimIn:
    return ev.ClaimIn(f"c{i}", attr, value, "PUBLICATION", domain)


async def test_two_agreeing_transmission_claims_give_the_gearbox_and_values_are_selected() -> None:
    store = FakeValues(["6-speed manual", "manual 6 velocidades"], [_claim(1, "max_power", 110.0, "a.es")])
    await ValueSelection(store).reselect("v")
    assert store.gearbox == "manual"
    power = next(v for v in store.selected if v.attribute == "max_power")
    assert power.available and power.value_num == 110.0 and power.claim_ids == ["c1"]


async def test_contradicting_gearboxes_leave_the_column_empty() -> None:
    store = FakeValues(["6-speed manual", "DSG 7"], [])
    selector = ValueSelection(store)
    await selector.reselect("v")
    assert store.gearbox is None
    assert await selector.gearboxes_mixed("v")


async def test_store_down_propagates() -> None:
    with pytest.raises(PipelineStoreUnavailable):
        await ValueSelection(FakeValues([], [], down=True)).reselect("v")


def test_the_schedule_gives_the_interval_when_no_source_states_it() -> None:
    schedule = [ScheduleItem("oil and filter", 15000, 12, ("https://www.hyundai.es/mantenimiento",))]
    rows = {v.attribute: v for v in selection.select_values([], schedule)}
    assert rows["service_interval_km"].value_num == 15000.0
    assert rows["service_interval_km"].resolution_rule == "schedule"


def test_positioning_vote_takes_the_most_stated_and_breaks_ties_alphabetically() -> None:
    assert selection.positioning_vote(["PREMIUM", "MAINSTREAM", "PREMIUM"]) == "PREMIUM"
    assert selection.positioning_vote(["PREMIUM", "MAINSTREAM"]) == "MAINSTREAM"
    assert selection.positioning_vote([]) is None
