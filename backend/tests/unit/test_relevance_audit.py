"""Spec 011 US5 gap "manuales": the pure parts of relevance auditing — the rule and trigger word of a stored rejection,
numbers on a page, the stop-phrase check, clusters, the measure and the replay/shadow decisions; the stop lists in the
relevance rules; the sense rules of a sense lever."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from automind.acquisition.domain import relevance as rel
from automind.acquisition.domain import relevance_audit as ra
from automind.acquisition.gates import evaluate

CFG = ra.RelevanceGateConfig()
REASON = "other gearbox: manual (wanted automatic)"


def test_rule_of_a_stored_reason() -> None:
    assert ra.rule_of("OTHER_VARIANT", REASON) == "gearbox.manual"
    assert ra.rule_of("OTHER_VARIANT", "other gearbox: automatic (wanted manual)") == "gearbox.automatic"
    assert ra.rule_of("OTHER_VARIANT", "other drive: AWD (wanted FWD)") == "drive.AWD"
    assert ra.rule_of("OTHER_VARIANT", "other generation: F10 (2010–2016)") == "other_generation"
    assert ra.rule_of("NOT_ABOUT_CAR", "the page does not name BMW Serie 5") == "not_about_car"
    assert ra.LEVER_OF["gearbox.manual"] == "relevance.keywords.not_manual"
    assert "other_generation" not in ra.LEVER_OF


def test_trigger_word_and_context() -> None:
    t = ra.title_url("BMW Serie 5 G30 520d Manual del vehículo | km77.com", "https://km77.com/bmw-serie-5/datos")
    assert ra.trigger("gearbox.manual", t) == ("manual", "manual del vehículo")
    assert ra.trigger("gearbox.automatic", "bmw 520d automática 8 vel") == ("automática", "automática 8 vel")
    assert ra.trigger("gearbox.manual", "bmw 520d manuales") is None  # whole words only
    assert ra.trigger("other_generation", t) is None


def test_numbers_in_both_formats() -> None:
    nums = ra.numbers("Peso 1.615 kg · 7,7 s · 190 CV / 140 kW · 1,995 cc")
    for x in (1615.0, 7.7, 140.0, 1995.0, 1.615):
        assert ra.contains_value(nums, x)
    assert not ra.contains_value(nums, 1700.0)


def test_stop_phrase_check() -> None:
    titles = ["bmw g30 manual del vehículo", "bmw 530d manual del vehículo pdf", "manual del vehículo 520i"]
    assert ra.stop_phrase_problem("Manual del vehículo", "manual", titles, [], 3) is None
    assert "2 to 4 words" in str(ra.stop_phrase_problem("manual", "manual", titles, [], 3))
    assert "does not contain" in str(ra.stop_phrase_problem("del vehículo", "manual", titles, [], 3))
    assert "occurs on 1" in str(ra.stop_phrase_problem("manual del vehículo pdf", "manual", titles, [], 3))
    assert "already" in str(ra.stop_phrase_problem("manual del vehículo", "manual", titles, ["manual del vehículo"], 3))


def _page(i: int, title: str, reason: str = REASON, verdict: str = "OTHER_VARIANT") -> ra.RejectedPage:
    return ra.RejectedPage(f"s{i}", f"v{i % 2}", f"https://km77.com/{i}", title, verdict, reason, ("max_power",))


def test_clusters_by_rule_and_trigger_word() -> None:
    pages = [_page(i, f"BMW 520d manual del vehículo {i}") for i in range(3)]
    pages += [_page(10 + i, "BMW 520d F10", "other generation: F10 (2010–2016)") for i in range(3)]
    pages += [_page(20, "BMW automática")]  # one page: no cluster
    got = ra.relevance_clusters(pages, 3)
    assert [(c.rule, c.word, len(c.pages), c.path) for c in got] == [
        ("gearbox.manual", "manual", 3, "relevance.keywords.not_manual"),
        ("other_generation", "", 3, None),
    ]
    assert got[0].contexts == {"manual del vehículo": 3} and got[0].variants == ["v0", "v1"]


def _checks() -> list[ra.PageCheck]:
    good = [ra.PageCheck(f"g{i}", "v", "OTHER_VARIANT", "RELEVANT", right=4, wrong=0, values=10) for i in range(4)]
    junk = [ra.PageCheck(f"j{i}", "v", "OTHER_VARIANT", "OTHER_VARIANT", right=1, wrong=3, values=10)
            for i in range(3)]  # fmt: skip
    return good + junk


def test_measure_from_pages() -> None:
    m = ra.RelevanceMeasure.from_pages(_checks())
    assert (m.pages, m.rejected_old, m.flipped, m.values_checked, m.values_right) == (7, 7, 4, 16, 16)
    assert (m.correct_rejections, m.junk_accepted, m.junk_rate, m.precision) == (3, 0, 0.0, 1.0)
    assert ra.RelevanceMeasure.from_dict(m.as_dict()) == m


def test_replay_verdicts() -> None:
    good = ra.RelevanceMeasure.from_pages(_checks())
    assert ra.relevance_replay_verdict(good, CFG, wait_days=7).verdict == "pass"
    bad = ra.RelevanceMeasure.from_pages([ra.PageCheck(c.snapshot_id, c.variant_id, c.old, "RELEVANT", c.right,
                                                       c.wrong, c.values) for c in _checks()])  # fmt: skip
    v = ra.relevance_replay_verdict(bad, CFG, wait_days=7)
    assert v.verdict == "fail" and "junk acceptance 3/3" in v.reason and "precision 19/28" in v.reason
    few = ra.RelevanceMeasure.from_pages(_checks()[:2] + _checks()[4:])
    assert ra.relevance_replay_verdict(few, CFG, wait_days=7).verdict == "insufficient_evidence"
    assert ra.relevance_replay_verdict(few, CFG, wait_days=7, waited_days=7).verdict == "abandon"
    lost = ra.RelevanceMeasure.from_pages([ra.PageCheck("x", "v", "RELEVANT", "OTHER_VARIANT", 3, 0, 5), *_checks()])
    assert "3 right values lost" in ra.relevance_replay_verdict(lost, CFG, wait_days=7).reason


def test_shadow_verdicts() -> None:
    m = ra.RelevanceMeasure.from_pages(_checks()[:3])
    kw = {"min_pages": 20, "decide_days": 3, "max_days": 7}
    assert ra.relevance_shadow_verdict(m, CFG, days=1, **kw).verdict == "wait"
    assert ra.relevance_shadow_verdict(m, CFG, days=4, **kw).verdict == "pass"
    assert ra.relevance_shadow_verdict(ra.RelevanceMeasure(), CFG, days=8, **kw).verdict == "abandon"
    assert ra.relevance_shadow_verdict(m, CFG, days=4, budget_left=False, **kw).verdict == "abandon"


def test_gate_config_from_agents_yaml() -> None:
    cfg = ra.RelevanceGateConfig.from_mapping({"gates": {"relevance": {"min_flipped": 5, "max_junk_rate": 0.1}}})
    assert (cfg.min_flipped, cfg.max_junk_rate, cfg.min_precision) == (5, 0.1, 0.9)
    assert ra.RelevanceGateConfig.from_mapping(None) == CFG


@pytest.fixture
def stop_lists():
    yield
    rel.configure_keywords({})


def test_stop_lists_loosen_the_gearbox_and_drive_rules(stop_lists) -> None:
    tgt = rel.Target("BMW", "Serie 5", "G30", 2017, 2023, "520d", "diesel", None, "automatic", "RWD")
    page = rel.PageFacts("https://km77.com/bmw-serie-5-g30", "BMW Serie 5 G30 520d manual del vehículo", "")
    assert rel.judge(page, tgt, []).verdict == "OTHER_VARIANT"
    rel.configure_keywords({"not_manual": ["manual del vehículo"]})
    assert rel.judge(page, tgt, []).verdict == "RELEVANT"
    manual_tgt = rel.Target("BMW", "Serie 5", "G30", 2017, 2023, "520d", "diesel", None, "manual", "RWD")
    club = rel.PageFacts("https://km77.com/bmw-serie-5-g30", "BMW Serie 5 G30 520d auto club test", "")
    assert rel.judge(club, manual_tgt, []).verdict == "OTHER_VARIANT"
    rel.configure_keywords({"not_auto": ["auto club"]})
    assert rel.judge(club, manual_tgt, []).verdict == "RELEVANT"
    integral = rel.PageFacts("https://km77.com/bmw-serie-5-g30", "BMW Serie 5 G30 520d prueba integral", "")
    assert rel.judge(integral, tgt, []).verdict == "OTHER_VARIANT"
    rel.configure_keywords({"not_awd": ["prueba integral"]})
    assert rel.judge(integral, tgt, []).verdict == "RELEVANT"


def test_a_sense_lever_has_an_offline_measure() -> None:
    c = SimpleNamespace(object_key="sense.magnitude.service_interval_km.max", status="replay",
                        diff={"from": 60000, "to": 70000})  # fmt: skip
    before, after = evaluate.rule_sets(c)  # type: ignore[arg-type]
    assert before["sense"]["magnitude"]["service_interval_km"]["max"] == 60000
    assert after["sense"]["magnitude"]["service_interval_km"]["max"] == 70000
    assert after["plausibility"] == before["plausibility"]
    with pytest.raises(evaluate.NoMeasure):
        evaluate.rule_sets(SimpleNamespace(object_key="relevance.keywords.not_manual", status="replay", diff={}))  # type: ignore[arg-type]
