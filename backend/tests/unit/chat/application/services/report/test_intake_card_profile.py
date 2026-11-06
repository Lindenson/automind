"""The intake card shows who the user is and how long they keep a car, with the basis (spec 007 US1, FR-015)."""

from automind.chat.application.services.report.intake_card import _profile_items, apply_edit
from automind.chat.domain.case import CaseFile, apply_defaults

DEFAULTS = {"personas": {"PERFORMANCE": {"ownership_years": 4, "annual_km": 12000},
                         "UNKNOWN": {"ownership_years": 5, "annual_km": 15000}}}  # fmt: skip


def _by_field(case, lang="ru"):
    return {i["field"]: i for i in _profile_items(case, lang)}


def test_inferred_persona_with_words_and_assumed_defaults():
    c = CaseFile(persona="PERFORMANCE", basis={"persona": "INFERRED"})
    c.profile.evidence["persona"] = "M Sport или Golf R"
    items = _by_field(apply_defaults(c, DEFAULTS))
    assert items["persona"]["basis"] == "INFERRED" and items["persona"]["evidence"] == "M Sport или Golf R"
    assert items["ownership_years"]["value"] == "4 года"
    assert items["ownership_years"]["basis"] == "ASSUMED" and items["annual_km"]["basis"] == "ASSUMED"
    assert len(items["persona"]["options"]) == 3


def test_card_chips_are_statements_applied_before_research():
    c = apply_defaults(CaseFile(), DEFAULTS)
    assert apply_edit(c, None, "persona", "семья и практичный покупатель", 2026) == ["persona: BUYER"]
    assert c.persona == "BUYER" and c.basis["persona"] == "STATED" and c.persona_source == "USER_EDIT"
    assert apply_edit(c, None, "ownership_years", "8 лет", 2026) == ["ownership: 8 years"]
    assert c.ownership_years == 8 and c.basis["ownership_years"] == "STATED"
    assert apply_edit(c, None, "annual_km", "30 000", 2026) == ["annual km 30,000"]
    assert c.basis["annual_km"] == "STATED"
    assert apply_edit(c, None, "ownership_years", "30 лет", 2026) == []
