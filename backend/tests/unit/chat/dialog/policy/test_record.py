"""A policy pass as a record (spec 015 T221, T223, T224): stable hashes, the record of a decision, the replay, the
"why" text and the masked fixture."""

from __future__ import annotations

import hashlib
import json
from importlib.metadata import version

from automind.chat.dialog.policy import (
    RULES,
    config_hash,
    config_json,
    decide,
    fixture,
    mask,
    record_of,
    render_why,
    replay,
    rules_version,
)
from automind.chat.domain.case import CaseCar, CaseFile
from automind.chat.domain.decision import CarState

from .builder import config, situation

CASE = CaseFile(cars=[CaseCar(key="car#1", request_text="мой гольф из Мадрида", make="Volkswagen", model="Golf",
                              variant_id="v1", resolution="CONFIRMED", condition="NEW")])  # fmt: skip
STALE = {"car#1": CarState(in_catalog=True, data_fresh=False, plausible_generations=1)}


def _decided(cost: float = 0.5):  # noqa: ANN202
    s = situation(CASE, "compare", STALE, cost_estimate_eur=cost, pass_no=2)
    return s, decide(s, config())


def test_one_config_has_one_hash_and_another_config_another() -> None:
    cfg = config()
    canonical = json.dumps(config_json(cfg), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert config_hash(cfg) == hashlib.sha256(canonical.encode()).hexdigest()
    assert config_hash(config()) == config_hash(cfg)
    assert config_hash(config(threshold=0.31)) != config_hash(cfg)


def test_the_rules_version_is_the_hash_of_the_rules_in_order_and_the_package_version() -> None:
    names = "|".join(r.name for r in RULES)
    assert hashlib.sha256(f"{names}@{version('automind')}".encode()).hexdigest() == rules_version()


def test_the_record_of_a_pass_keeps_everything_but_the_case() -> None:
    s, d = _decided()
    rec = record_of(d, s, config(), chat_id="c1", turn_id="t1", case_version=7)
    assert (rec.pass_no, rec.case_version, rec.decided_by, rec.next_node) == (2, 7, "stale_data", "prepare_cost")
    assert rec.action["kind"] == "CONFIRM_COST" and "case" not in rec.situation
    assert rec.situation["cost_estimate_eur"] == "0.50" and rec.trail[-1].fired and not rec.trail[0].fired
    assert [t.rule for t in rec.trail] == [r.name for r in RULES][: len(rec.trail)]


def test_a_replayed_pass_decides_the_same() -> None:
    s, d = _decided()
    rec = record_of(d, s, config(), chat_id="c1", turn_id="t1", case_version=7)
    again = replay(rec, CASE, config())
    assert again == d
    text = render_why([rec], {2: again})
    assert "pass 2 on case v7" in text and "✓ stale_data" in text and "replay: same" in text
    differs = render_why([rec], {2: replay(rec, CASE, config(threshold=0.9, cap=1.0))})
    assert "replay: differs: today RESEARCH by stale_data" in differs


def test_no_record_says_so() -> None:
    assert render_why([]) == "no policy decisions recorded for this turn"


def test_a_fixture_masks_the_persons_words_and_still_decides_the_same() -> None:
    s, d = _decided()
    rec = record_of(d, s, config(), chat_id="c1", turn_id="t1", case_version=7)
    fx = fixture(rec, CASE, config_json(config()))
    assert "гольф" not in json.dumps(fx, ensure_ascii=False)
    assert fx["situation"]["case"]["cars"][0]["request_text"] == "<masked>"
    action = {k: v for k, v in rec.action.items() if k != "reason"}
    assert fx["expected"] == {"decided_by": "stale_data", "action": action}
    assert decide(s.model_copy(update={"case": mask(CASE)}), config()).action == d.action
