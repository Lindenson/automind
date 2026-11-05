"""Spec 011 T093 (research R14): the pure gate decisions — replay, shadow, watch — and the one-sentence explanation."""

from __future__ import annotations

import pytest

from automind.acquisition.domain.gates import (
    Facts,
    GateConfig,
    Metrics,
    explain,
    replay_verdict,
    shadow_verdict,
    watch_verdict,
)

CFG = GateConfig()
OLD = Metrics(pages=50, yield_=10.0, pass_rate=0.80, gold_covered=50, gold_match=46, accuracy_lb=0.82,
              coverage=12.0, cost_per_value=0.001, freshness_days=1.0)  # fmt: skip


def new(**kw: object) -> Metrics:
    base = dict(pages=50, yield_=10.5, pass_rate=0.80, gold_covered=50, gold_match=46, accuracy_lb=0.82,
                coverage=12.0, cost_per_value=0.001, freshness_days=1.0)  # fmt: skip
    return Metrics(**{**base, **kw})  # type: ignore[arg-type]


def test_config_from_agents_yaml_mapping() -> None:
    cfg = GateConfig.from_mapping({
        "gates": {"replay": {"min_gold": 5, "kpi_slack": 0.02, "better": {"yield": 0.1, "accuracy": 0.03,
                                                                          "pass_rate": 0.04},
                             "guards": {"coverage_drop": 0.05, "cost_rise": 0.2}, "min_accuracy_lb": 0.7,
                             "wait_days": 3},
                  "watch": {"accuracy_lb_drop": 0.05, "yield_drop": 0.3, "wrong_signals": 2}},
        "watch_days": 4, "shadow": {"min_pages": 10, "max_days": 5},
    })  # fmt: skip
    assert (cfg.min_gold, cfg.kpi_slack, cfg.better_yield, cfg.better_accuracy, cfg.better_pass_rate) == (
        5, 0.02, 0.1, 0.03, 0.04)  # fmt: skip
    assert (cfg.coverage_drop, cfg.cost_rise, cfg.min_accuracy_lb, cfg.wait_days) == (0.05, 0.2, 0.7, 3)
    assert (cfg.watch_accuracy_lb_drop, cfg.watch_yield_drop, cfg.watch_wrong_signals, cfg.watch_days) == (
        0.05, 0.3, 2, 4)  # fmt: skip
    assert (cfg.shadow_min_pages, cfg.shadow_max_days) == (10, 5)
    assert GateConfig.from_mapping(None) == GateConfig()


def test_metrics_from_a_replay_report() -> None:
    m = Metrics.from_report({"pages": 20, "yield": 9.5, "pass_rate": 0.9, "gold_covered": 50, "gold_match": 48,
                             "accuracy_lb": 0.86, "extra": 1})  # fmt: skip
    assert (m.pages, m.yield_, m.gold_covered, m.gold_match, m.accuracy) == (20, 9.5, 50, 48, 0.96)
    assert Metrics.from_report(m.as_dict()) == m


# --- replay ---------------------------------------------------------------------------------------------------------


def test_replay_passes_when_kpi_holds_one_target_is_better_and_guards_hold() -> None:
    v = replay_verdict(OLD, new(yield_=10.05), CFG)
    assert v.verdict == "pass" and v.better == ("yield",)


@pytest.mark.parametrize(
    ("kw", "target"),
    [({"yield_": 10.05}, "yield"), ({"gold_match": 48, "yield_": 10.0}, "accuracy"),
     ({"pass_rate": 0.85, "yield_": 10.0}, "pass_rate")],
)  # fmt: skip
def test_each_target_metric_counts(kw: dict, target: str) -> None:
    v = replay_verdict(OLD, new(**kw), CFG)
    assert v.verdict == "pass" and target in v.better


def test_replay_fails_without_a_better_target() -> None:
    v = replay_verdict(OLD, new(yield_=10.01), CFG)
    assert v.verdict == "fail" and any("no target metric better" in r for r in v.reasons)


def test_replay_fails_when_better_on_yield_but_worse_on_accuracy() -> None:
    """US5 AS-2: a proposal better on yield but worse on accuracy against gold is rejected."""
    v = replay_verdict(OLD, new(yield_=14.0, gold_match=40, accuracy_lb=0.66), CFG)
    assert v.verdict == "fail" and v.better == ("yield",)
    assert any(r.startswith("accuracy_lb 0.66 < 0.81") for r in v.reasons)


def test_kpi_slack_allows_a_tiny_accuracy_loss() -> None:
    assert replay_verdict(OLD, new(accuracy_lb=0.811), CFG).verdict == "pass"
    assert replay_verdict(OLD, new(accuracy_lb=0.809), CFG).verdict == "fail"


@pytest.mark.parametrize(
    ("kw", "guard"),
    [({"coverage": 11.7}, "coverage"), ({"cost_per_value": 0.00111}, "cost per value"),
     ({"freshness_days": 1.5}, "freshness")],
)  # fmt: skip
def test_each_guard_fails_the_replay(kw: dict, guard: str) -> None:
    v = replay_verdict(OLD, new(**kw), CFG)
    assert v.verdict == "fail" and any(r.startswith(guard) for r in v.reasons)


def test_guards_within_tolerance_pass() -> None:
    assert replay_verdict(OLD, new(coverage=11.8, cost_per_value=0.00109), CFG).verdict == "pass"


def test_insufficient_evidence_below_min_gold_then_abandoned() -> None:
    v = replay_verdict(OLD, new(gold_covered=19, gold_match=19), CFG, waited_days=1)
    assert v.verdict == "insufficient_evidence" and "19 gold values" in v.reasons[0]
    assert replay_verdict(OLD, new(gold_covered=19), CFG, waited_days=7).verdict == "abandon"


def test_degraded_object_uses_new_accuracy_alone() -> None:
    """R14: on a degraded object (old yield ≈ 0) the KPI is the new version's gold accuracy ≥ min_accuracy_lb."""
    broken = Metrics(pages=20, yield_=0.0, pass_rate=0.0, gold_covered=0, gold_match=0, accuracy_lb=None)
    good = new(yield_=9.0, gold_covered=50, gold_match=48, accuracy_lb=0.86)
    assert replay_verdict(broken, good, CFG).verdict == "pass"  # old yield ≈ 0 → degraded by itself
    worse = new(yield_=9.0, gold_covered=50, gold_match=38, accuracy_lb=0.63)
    v = replay_verdict(broken, worse, CFG)
    assert v.verdict == "fail" and any("< 0.80 (degraded object)" in r for r in v.reasons)
    # a flagged degraded object compares with min_accuracy_lb even when the old version still reads something
    old = Metrics(pages=20, yield_=3.0, pass_rate=0.9, gold_covered=40, gold_match=40, accuracy_lb=0.91)
    assert replay_verdict(old, good, CFG, degraded=True).verdict == "pass"
    assert replay_verdict(old, good, CFG).verdict == "fail"  # not degraded: 0.86 < 0.91 − 0.01


# --- shadow ---------------------------------------------------------------------------------------------------------


def test_shadow_waits_for_pages_then_decides() -> None:
    assert shadow_verdict(OLD, new(pages=5), CFG, days=1).verdict == "wait"
    assert shadow_verdict(OLD, new(pages=20, yield_=11.0), CFG, days=1).verdict == "pass"
    assert shadow_verdict(OLD, new(pages=5, yield_=11.0), CFG, days=3).verdict == "pass"  # 3 days: decide anyway
    assert shadow_verdict(OLD, new(pages=20, yield_=10.0), CFG, days=1).verdict == "fail"


def test_shadow_abandons_on_budget_or_time() -> None:
    v = shadow_verdict(OLD, new(pages=5), CFG, days=1, budget_left=False)
    assert v.verdict == "abandon" and "budget" in v.reasons[0]
    v = shadow_verdict(OLD, new(pages=0), CFG, days=7)
    assert v.verdict == "abandon" and "7 days" in v.reasons[0]
    assert shadow_verdict(OLD, new(pages=0), CFG, days=4).verdict == "wait"  # nothing read yet: keep waiting


def test_shadow_without_enough_gold_judges_on_yield_and_pass_rate() -> None:
    v = shadow_verdict(OLD, new(pages=20, yield_=11.0, gold_covered=3, gold_match=1, accuracy_lb=0.1), CFG, days=1)
    assert v.verdict == "pass"  # accuracy was proved on gold at replay; 3 values say nothing


# --- watch ----------------------------------------------------------------------------------------------------------


BASE = Metrics(pages=20, yield_=10.0, pass_rate=0.9, gold_covered=50, gold_match=48, accuracy_lb=0.86)


def test_watch_keeps_after_watch_days_and_waits_before() -> None:
    assert watch_verdict(BASE, BASE, 0, 2, CFG).verdict == "wait"
    assert watch_verdict(BASE, BASE, 2, 7, CFG).verdict == "keep"


@pytest.mark.parametrize(
    ("current", "wrong", "reason"),
    [(BASE, 3, "3 wrong values blamed"), (Metrics(pages=10, yield_=10.0, accuracy_lb=0.82, gold_covered=30), 0,
                                          "accuracy_lb 0.82 vs 0.86"),
     (Metrics(pages=10, yield_=7.9, accuracy_lb=0.86, gold_covered=30), 0, "yield 7.90 vs 10.00")],
)  # fmt: skip
def test_watch_rolls_back_on_each_trigger(current: Metrics, wrong: int, reason: str) -> None:
    v = watch_verdict(BASE, current, wrong, 2, CFG)
    assert v.verdict == "rollback" and any(r.startswith(reason) for r in v.reasons)


def test_watch_ignores_a_day_without_pages() -> None:
    assert watch_verdict(BASE, Metrics(), 0, 2, CFG).verdict == "wait"


# --- explanation ----------------------------------------------------------------------------------------------------


def test_explain_accepted_parser_in_one_sentence() -> None:
    f = Facts("parser", "km77", "km77@v4", "km77@v5", "table labels changed on 03.11", "accepted")
    replay = Metrics(gold_covered=50, gold_match=48)
    shadow = (Metrics(pages=20, yield_=0.42), Metrics(pages=20, yield_=0.91))
    assert explain(f, replay=replay, shadow=shadow) == (
        "km77 parser v4→v5: table labels changed on 03.11; v5 reproduces 48/50 gold values; shadow yield 0.91 vs 0.42"
    )


def test_explain_rolled_back() -> None:
    f = Facts("parser", "km77", "km77@v4", "km77@v5", "", "rolled_back")
    v = watch_verdict(BASE, BASE, 3, 2, CFG)
    assert explain(f, verdict=v, wrong_signals=3, days=2) == (
        "km77 parser v5 rolled back: 3 wrong values blamed to v5 in 2 days; previous v4 restored"
    )


def test_explain_rejected_names_the_gate_and_the_reason() -> None:
    f = Facts("parser", "km77", "km77@v1", "km77@v3", "structure changed on 30.06", "rejected", gate="replay")
    v = replay_verdict(OLD, new(yield_=14.0, gold_match=40, accuracy_lb=0.66), CFG)
    s = explain(f, verdict=v, replay=new(gold_match=40))
    assert s.startswith("km77 parser v1→v3 rejected at replay: accuracy_lb 0.66 < 0.81")
    assert s.endswith("; v3 reproduces 40/50 gold values") and "\n" not in s


@pytest.mark.parametrize(
    ("facts", "start"),
    [(Facts("prompt", "extract_specs", "extract_specs@v2", "extract_specs@v3", "accuracy fell", "proposed"),
      "extract_specs prompt v2→v3: accuracy fell"),
     (Facts("role_model", "extractor", "google_genai:a", "google_genai:b", "yield fell", "proposed"),
      "extractor model google_genai:a→google_genai:b: yield fell"),
     (Facts("rule", "plausibility.by_powertrain.consumption.BEV.max", "35", "38", "7 values confirmed", "proposed"),
      "rule plausibility.by_powertrain.consumption.BEV.max 35→38: 7 values confirmed")],
)  # fmt: skip
def test_explain_other_levers(facts: Facts, start: str) -> None:
    assert explain(facts).startswith(start)
