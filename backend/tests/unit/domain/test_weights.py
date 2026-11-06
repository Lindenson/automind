"""Weights from the profile, with reasons; manual weights as adjustments (spec 007 US2, SC-003)."""

import pytest

from automind.chat.domain.assessment import weights as w
from automind.chat.domain.assessment.criteria import (
    CriteriaModel,
    reset_weights,
    set_manual_weights,
    weight_breakdown,
    weights_for,
)
from automind.chat.domain.case.casefile import CaseFile, Priority
from automind.shared.infrastructure.config.loader import load_yaml

MODEL = CriteriaModel.from_config(load_yaml("criteria.yaml"), load_yaml("profile_rules.yaml"))
RULES = MODEL.rules


def _case(**kw):
    basis = kw.pop("basis", {})
    c = CaseFile(**kw)
    c.basis.update(basis)
    return c


def test_every_rule_in_the_file_adds_its_points_with_its_reason():
    for field, by_value in RULES.rules.items():
        for value, pts in by_value.items():
            if field in ("family", "driving_style"):
                c = _case(profile={field: value, "evidence": {field: "x"}}, basis={field: "STATED"})
            elif field == "usage":
                c = _case(usage=[value], basis={"usage": "STATED"})
            elif field == "climate":
                c = _case(profile={"climate": value, "region": "x"}, basis={"region": "STATED"})
            elif field == "annual_km":
                km = 30000 if value.startswith(">") else 6000
                c = _case(annual_km=km, basis={"annual_km": "STATED"})
            elif field == "ownership_years":
                c = _case(ownership_years=10 if value.startswith(">") else 2, basis={"ownership_years": "STATED"})
            else:
                c = _case(budget={"intent": "USED"})
            codes = {code for code, _ in w.matched_rules(c, RULES)}
            assert f"{field}.{value}" in codes, (field, value)
            b = weight_breakdown(c, MODEL)
            for k in pts:
                assert any(code == f"{field}.{value}" for code, _ in b.lines[k].contributions), (field, value, k)


def test_assumed_fields_never_move_a_weight():
    c = _case(annual_km=30000, ownership_years=10)  # both ASSUMED
    assert w.matched_rules(c, RULES) == []


def test_different_profiles_same_persona_give_different_weights():
    fam = _case(persona="BUYER", profile={"family": "FAMILY", "driving_style": "CALM",
                                          "evidence": {"family": "дети", "driving_style": "спокойно"}},
                usage=["MOUNTAINS"],
                basis={"family": "INFERRED", "driving_style": "STATED", "usage": "STATED"})  # fmt: skip
    solo = _case(persona="BUYER", profile={"family": "SINGLE", "driving_style": "SPORTY",
                                           "evidence": {"family": "один", "driving_style": "люблю быстро"}},
                 usage=["CITY"], basis={"family": "STATED", "driving_style": "STATED", "usage": "STATED"})  # fmt: skip
    a, b = weights_for(fam, MODEL), weights_for(solo, MODEL)
    assert a != b
    assert a.get("practicality", 0) > b.get("practicality", 0) and b.get("performance", 0) > a.get("performance", 0)
    assert round(sum(a.values()), 3) == 100 and round(sum(b.values()), 3) == 100


def test_cap_and_normalisation():
    sporty = {"driving_style": "SPORTY", "evidence": {"driving_style": "x"}}
    c = _case(persona="PERFORMANCE", usage=["TRACK"], profile=sporty,
              basis={"usage": "STATED", "driving_style": "STATED"},
              priorities=[Priority(criterion="performance", strength="HIGH")])  # fmt: skip
    final = weights_for(c, MODEL)
    assert max(final.values()) <= RULES.cap + 1e-6 and round(sum(final.values()), 3) == 100


def test_manual_adjustment_survives_a_persona_change_and_reset_removes_it():
    c = _case(persona="BUYER", basis={"persona": "STATED"})
    auto = weights_for(c, MODEL)
    wanted = {**auto, "safety": auto.get("safety", 0) + 20}
    c = set_manual_weights(c, wanted, MODEL)
    got = weights_for(c, MODEL)
    assert got["safety"] == pytest.approx(wanted["safety"] * 100 / sum(wanted.values()), abs=0.01)
    assert weight_breakdown(c, MODEL).manual
    c2 = c.model_copy(update={"persona": "PERFORMANCE"})
    perf_auto = weights_for(c2.model_copy(update={"weight_adjustments": {}}), MODEL)
    after = weights_for(c2, MODEL)
    assert after != perf_auto and after.get("performance", 0) > 0  # the rest followed the persona
    assert after.get("safety", 0) > perf_auto.get("safety", 0)  # the user's extra safety stayed
    assert weights_for(reset_weights(c2), MODEL) == perf_auto


def test_manual_zero_excludes_the_criterion_for_good():
    c = _case(persona="BUYER")
    auto = weights_for(c, MODEL)
    c = set_manual_weights(c, {**auto, "reliability": 0}, MODEL)
    assert "reliability" not in weights_for(c, MODEL)
    assert "reliability" not in weights_for(c.model_copy(update={"persona": "EXPERT"}), MODEL)
    assert weight_breakdown(c, MODEL).excluded == ("reliability",)


def test_legacy_absolute_weights_read_the_same():
    old = CaseFile(persona="BUYER", weights={"reliability": 60, "status": 40}, weights_overridden=True)
    assert weights_for(old, MODEL) == pytest.approx({"reliability": 60, "status": 40}, abs=0.01)


def test_loader_rejects_unknown_criteria_fields_and_bands():
    with pytest.raises(ValueError):
        w.ProfileRules.from_config({"rules": {"family": {"FAMILY": {"colour": 5}}}})
    with pytest.raises(ValueError):
        w.ProfileRules.from_config({"rules": {"zodiac": {"LEO": {"safety": 5}}}})
    with pytest.raises(ValueError):
        w.ProfileRules.from_config({"rules": {"annual_km": {"lots": {"efficiency": 5}}}})


def test_every_reason_code_has_an_interface_label():
    from pathlib import Path

    en = (Path(__file__).resolve().parents[4] / "frontend" / "src" / "i18n" / "en.ts").read_text(encoding="utf-8")
    codes = [f"{f}.{v}" for f, by in RULES.rules.items() for v in by] + [f"priority.{s}" for s in MODEL.strength_points]
    missing = [c for c in codes if f'"reason.{c}"' not in en]
    assert not missing, missing
