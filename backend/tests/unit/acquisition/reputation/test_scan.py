"""`SignalScan` and `DailyRollup` over fakes: a failing rule kind never stops the others, a store that cannot be read
fails the scan, disputed signals queue judges, the gauges are best effort."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from automind.acquisition.registry.api import TruthSignalIn
from automind.acquisition.reputation.application.errors import ReputationStoreUnavailable
from automind.acquisition.reputation.application.rollup import DailyRollup, DayCounts
from automind.acquisition.reputation.application.signals import SignalScan
from automind.acquisition.reputation.domain.components import Weights
from automind.acquisition.reputation.domain.rollup import AreaTotals, AttemptCounts, DailyValues
from automind.acquisition.reputation.domain.signal_facts import ClaimFact, GoldFact, Tolerance, VariantFacts

T0 = datetime(2026, 11, 1, tzinfo=UTC)


class _Facts:
    def __init__(self, facts: VariantFacts | None, *, down: bool = False) -> None:
        self.f, self.down = facts, down

    async def facts(self, variant_id: str) -> VariantFacts | None:
        if self.down:
            raise ReputationStoreUnavailable("claims: OperationalError")
        return self.f

    async def recent_variants(self, since: datetime) -> list[str]:
        return ["v1"]


class _Pages:
    async def snapshot_text(self, snapshot_id: str) -> str | None:
        return None


class _Tols:
    def of(self, attribute: str) -> Tolerance:
        return ("rel", 0.02)


class _Sink:
    def __init__(self) -> None:
        self.got: list[TruthSignalIn] = []

    async def signal(self, s: TruthSignalIn) -> str | None:
        self.got.append(s)
        return f"s{len(self.got)}"


class _Judges:
    def __init__(self) -> None:
        self.ids: list[str] = []

    async def judge(self, signal_ids: list[str]) -> int:
        self.ids += signal_ids
        return len(signal_ids)


class _Clock:
    def now(self) -> datetime:
        return T0


def _facts() -> VariantFacts:
    claims = (ClaimFact("c1", "max_power", 150, "specs", "a.com", "a", T0),
              ClaimFact("c2", "max_power", 150.5, "specs", "b.com", "b", T0))  # fmt: skip
    return VariantFacts("v1", "petrol", "ICE", None, claims, {}, {"max_power": GoldFact("g1", 150, None, None, "HIGH")})


def _scan(facts: _Facts, sink: _Sink, checks: object = None) -> SignalScan:
    return SignalScan(facts, _Pages(), _Tols(), sink, _Judges(), _Clock(), checks)  # type: ignore[arg-type]  # a bad config section on purpose


async def test_signals_are_sent_once_per_finding_and_counted() -> None:
    sink = _Sink()
    out = await _scan(_Facts(_facts()), sink, {}).scan(["v1"], judge=False)
    assert out == {"gold_right": 2, "agreement": 2, "variants": 1, "disputed": 0}
    assert {s.claim_id for s in sink.got if s.kind == "gold"} == {"c1", "c2"} and sink.got[0].gold_id == "g1"


async def test_a_failing_kind_never_stops_the_others() -> None:
    sink = _Sink()
    out = await _scan(_Facts(_facts()), sink, None).scan(["v1"], judge=False)  # physics fails on a missing config
    assert out["gold_right"] == 2 and out["agreement"] == 2


async def test_a_store_that_cannot_be_read_fails_the_scan() -> None:
    with pytest.raises(ReputationStoreUnavailable):
        await _scan(_Facts(None, down=True), _Sink(), {}).scan()


class _Store:
    def __init__(self) -> None:
        self.written: dict[date, dict[tuple[str, str], DailyValues]] = {}
        self.reset = False

    async def day_counts(self, day: date) -> DayCounts:
        return DayCounts([AttemptCounts("specs", "ES", 1, 4, 2, 0.01, 0.0)], [], [])

    async def write_day(self, day: date, rows: dict[tuple[str, str], DailyValues]) -> None:
        self.written[day] = rows

    async def area_totals(self, since: date, until: date) -> list[AreaTotals]:
        return [AreaTotals("specs", 2, 4, 1)]

    async def reset_exploration(self) -> None:
        self.reset = True


class _Components:
    async def decay_all(self, half_life_days: float) -> int:
        return 3

    async def weights(self) -> list[tuple[str, Weights]]:
        return [("parser", Weights(1.0, 0.0, T0, 0.5))]


class _Baselines:
    async def last_closed_wrong_share(self) -> dict[str, float]:
        return {}


class _BrokenGauges:
    def set_reputation(self, searches_per_value: dict[str, float], wrong_share: dict[str, float],
                       components: dict[str, float], baseline_wrong_share: dict[str, float]) -> None:  # fmt: skip
        raise RuntimeError("exporter down")


class _Today:
    def today(self) -> date:
        return date(2026, 11, 7)


async def test_rollup_writes_yesterday_and_today_and_survives_broken_gauges() -> None:
    store = _Store()
    out = await DailyRollup(store, _Components(), _Baselines(), _BrokenGauges(), _Today(), 30.0).run()
    assert set(store.written) == {date(2026, 11, 6), date(2026, 11, 7)} and store.reset
    assert out == {"days": ["2026-11-06", "2026-11-07"], "rows": 2, "components_faded": 3}
    assert (await DailyRollup(store, _Components(), _Baselines(), _BrokenGauges(), _Today(), 30.0).kpis(
        date(2026, 11, 1) - timedelta(days=0)))["wrong_share"] == {"specs": 0.25}  # fmt: skip
