"""Spec 011 T082 (research R12, FR-016): the three drift detectors and the sudden-zero rule, pure."""

from __future__ import annotations

from datetime import date, timedelta

from automind.acquisition.domain import drift
from automind.acquisition.domain.drift import DayStat, DriftConfig

TODAY = date(2026, 11, 5)
CFG = DriftConfig()


def _days(n: int, *, pages: int, fields: float, read: int = 10, accepted: int = 9, start: int = 0, sim=1.0):
    """`n` days ending `start` days before TODAY."""
    return [
        DayStat(day=TODAY - timedelta(days=start + i), pages=pages, fields_total=round(fields * pages),
                rows_read=read, rows_accepted=accepted, zero_pages=0, structure_sim=sim)
        for i in range(n)
    ]  # fmt: skip


def test_healthy_reader_has_no_verdict():
    assert drift.verdict(_days(37, pages=5, fields=12), TODAY, CFG) is None


def test_yield_drop():
    days = _days(7, pages=3, fields=6) + _days(30, pages=5, fields=12, start=7)
    v = drift.verdict(days, TODAY, CFG)
    assert v is not None and v.kind == "yield_drop"
    assert "6.0" in v.reason and "12.0" in v.reason and "50 %" in v.reason


def test_small_yield_drop_is_no_drift():
    days = _days(7, pages=3, fields=10) + _days(30, pages=5, fields=12, start=7)
    assert drift.verdict(days, TODAY, CFG) is None


def test_pass_rate_drop():
    days = _days(7, pages=3, fields=12, read=10, accepted=6) + _days(30, pages=5, fields=12, start=7)
    v = drift.verdict(days, TODAY, CFG)
    assert v is not None and v.kind == "pass_drop"
    assert "0.60" in v.reason and "0.90" in v.reason


def test_structure_change_without_yield_drop():
    days = (
        _days(1, pages=3, fields=12, sim=0.35)
        + _days(6, pages=3, fields=12, start=1)
        + _days(30, pages=5, fields=12, start=7)
    )
    v = drift.verdict(days, TODAY, CFG)
    assert v is not None and v.kind == "structure"
    assert v.reason.startswith("structure changed") and "0.35" in v.reason


def test_structure_change_with_yield_drop_names_both():
    days = _days(1, pages=15, fields=3, sim=0.1) + _days(30, pages=5, fields=12, start=7)
    v = drift.verdict(days, TODAY, CFG)
    assert v is not None and v.kind == "structure"
    assert "structure changed" in v.reason and "fields per page 3.0" in v.reason and "12.0" in v.reason
    assert set(v.signals) == {"structure", "yield_drop"}


def test_too_few_pages_no_verdict():
    days = _days(7, pages=2, fields=1, sim=0.1) + _days(30, pages=5, fields=12, start=7)  # 14 pages in 7 days
    assert drift.verdict(days, TODAY, CFG) is None


def test_no_baseline_no_yield_verdict():
    assert drift.verdict(_days(7, pages=3, fields=1), TODAY, CFG) is None


def test_zero_streak():
    assert drift.zero_streak(4, CFG) is None
    v = drift.zero_streak(5, CFG)
    assert v is not None and v.kind == "zero_streak" and "5 pages in a row" in v.reason


def test_config_from_yaml():
    c = DriftConfig.from_mapping({"min_pages_7d": 20, "yield_drop": 0.5, "zero_streak": 3})
    assert (c.min_pages_7d, c.yield_drop, c.pass_drop, c.zero_streak) == (20, 0.5, 0.15, 3)
