"""Persona and profile need the user's own words, from this or an earlier message (spec 007 FR-002)."""

from automind.chat.application.services.interpretation.interpret import Interpretation, _persona_from_users_words


def interp(evidence):
    return Interpretation.model_validate(
        {
            "request": "follow_up_question",
            "language": "en",
            "persona_evidence": evidence,
            "delta": {"set_persona": {"persona": "PERFORMANCE", "source": "ASKED"}},
        }
    )


def test_persona_kept_when_the_user_wrote_the_words():
    assert _persona_from_users_words(interp("race enthusiast"), ["the same for a race enthusiast"]).delta.set_persona
    # inferred from an earlier message of the dialogue (spec 007 FR-002)
    said = ["and now?", "compare bmw 320d m sport and golf r, I am a race enthusiast"]
    assert _persona_from_users_words(interp("race enthusiast"), said).delta.set_persona


def test_persona_dropped_without_the_users_words():
    assert _persona_from_users_words(interp("race enthusiast"), ["and now?"]).delta.set_persona is None
    assert _persona_from_users_words(interp(None), ["and now?"]).delta.set_persona is None


def test_profile_field_dropped_when_the_words_were_never_written():
    from automind.chat.application.services.interpretation.interpret import _profile_from_users_words

    i = Interpretation.model_validate({"request": "compare", "language": "ru", "delta": {"set_profile": {
        "family": "FAMILY", "driving_style": "CALM",
        "evidence": {"family": "вожу детей в школу", "driving_style": "езжу спокойно"}}}})  # fmt: skip
    out = _profile_from_users_words(i, ["вожу детей в школу, по выходным в горы"]).delta.set_profile
    assert out.family == "FAMILY" and out.driving_style is None and "driving_style" not in out.evidence


def test_numbers_with_russian_and_spanish_words():
    from automind.chat.application.services.interpretation.interpret import numbers_in

    assert numbers_in("до 20 тыщ") == {20000}
    assert numbers_in("1,5 млн") == {1500000}
    assert numbers_in("бюджет 20к") == {20000}
    assert numbers_in("Golf 7 2015") == {7, 2015}  # never 72015
    assert numbers_in("25.000 €") == {25000}
    assert numbers_in("20 км") == {20}  # a distance, not money
    assert numbers_in("1,5 millones") == {1500000}


def test_constraint_numbers_must_be_in_this_message():
    from automind.chat.application.services.interpretation.interpret import (
        Interpretation,
        _constraints_from_this_message,
        numbers_in,
    )
    from automind.chat.domain.case.casefile import Budget, CaseDelta, Needs, RunningLimit

    assert {25000.0, 150.0} <= numbers_in("tengo 25.000 € y no más de 150 al mes")
    assert 25000.0 in numbers_in("бюджет 25 тыс") and 25000.0 in numbers_in("budget 25k")
    i = Interpretation(request="compare", language="en", delta=CaseDelta(
        set_budget=Budget(max_eur=30000, intent="NEW"), set_running_cost_limit=RunningLimit(amount_eur=150),
        set_needs=Needs(passengers=4, towing_kg=1500)))  # fmt: skip
    out = _constraints_from_this_message(i, "a new one, up to 150 a month to run, we are 4")
    assert out.delta.set_budget.max_eur is None and out.delta.set_budget.intent == "NEW"  # 30000 not in the text
    assert out.delta.set_running_cost_limit.amount_eur == 150
    assert out.delta.set_needs.passengers == 4 and out.delta.set_needs.towing_kg is None


def test_cyrillic_k_thousands_not_km():
    from automind.chat.application.services.interpretation.interpret import numbers_in

    assert 20000.0 in numbers_in("бюджет 20к")
    assert 20000.0 not in numbers_in("20 км в день") and 20.0 in numbers_in("20 км в день")
