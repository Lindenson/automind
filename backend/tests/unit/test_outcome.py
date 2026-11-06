"""Spec 010 US1: failure classes and score of a turn (domain/outcome.py)."""

from __future__ import annotations

import yaml

from automind.observability.domain.outcome import FailureClass as F
from automind.observability.domain.outcome import TurnFacts, classes, score
from automind.shared.infrastructure.config.settings import settings

W = yaml.safe_load((settings().config_dir / "outcome.yaml").read_text(encoding="utf-8"))


def facts(**kw: object) -> TurnFacts:
    base: dict[str, object] = {"status": "DONE", "action": "REPORT"}
    base.update(kw)
    return TurnFacts(**base)  # type: ignore[arg-type]


def test_rating_wins_over_signals():
    assert score(facts(rating=5, relation_next="complaint", signals={"wrong_value": 3}), W) == 1.0
    assert score(facts(rating=1, relation_next="thanks"), W) == 0.0
    assert score(facts(rating=3), W) == 0.5


def test_rephrase_lowers_thanks_raises():
    plain = score(facts(), W)
    assert score(facts(relation_next="rephrase"), W) < 0.5 < plain
    assert score(facts(relation_next="thanks"), W) > plain


def test_classes_follow_the_spec_table():
    assert classes(facts(relation_next="rephrase")) == {F.NOT_UNDERSTOOD}
    assert classes(facts(relation_next="correction")) == {F.NOT_UNDERSTOOD}
    assert classes(facts(signals={"wrong_car": 1})) == {F.WRONG_CAR}
    assert classes(facts(signals={"no_data": 2})) == {F.NO_DATA}
    assert classes(facts(signals={"wrong_value": 1})) == {F.WRONG_DATA}
    assert classes(facts(signals={"bad_source": 1})) == {F.WRONG_DATA}
    assert classes(facts(signals={"guard_removed": 2})) == {F.BAD_TEXT}
    assert classes(facts(relation_next="complaint")) == {F.BAD_TEXT}
    assert classes(facts(status="FAILED")) == {F.PROCESS_FAILURE}
    assert classes(facts(signals={"process_failure": 1})) == {F.PROCESS_FAILURE}
    assert classes(facts(signals={"too_costly": 1})) == {F.TOO_COSTLY}
    assert classes(facts(relation_next="thanks")) == set()


def test_failed_turn_scores_low_and_clamps():
    assert score(facts(status="FAILED"), W) <= 0.1
    many = {k: 5 for k in ("wrong_value", "bad_source", "no_data", "guard_removed", "wrong_car", "too_costly")}
    assert score(facts(status="FAILED", relation_next="complaint", signals=many), W) == 0.0
    assert 0.0 <= score(facts(relation_next="thanks", signals={"continues": 1}), W) <= 1.0


def test_last_turn_without_next_message_uses_own_signals():
    f = facts(relation_next=None)
    assert score(f, W) == min(1.0, W["start"] + W["weights"]["report_reached"])
