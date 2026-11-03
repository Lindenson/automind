from automind.orchestration.phrases import PHRASES, t


def test_every_phrase_has_en_ru_es():
    for key, table in PHRASES.items():
        assert {"en", "ru", "es"} <= set(table), key


def test_language_fallback_and_formatting():
    assert t("confirm_variants", "ru").startswith("Прежде")
    assert t("confirm_variants", "de") == PHRASES["confirm_variants"]["en"]
    assert "€0.42" in t("confirm_cost", "en", cars="A", depth="standard", eur="0.42", cap="")


def test_guess_language_from_the_users_words():
    from automind.orchestration.phrases import guess_language

    assert guess_language(["сравни RAV4 и CX-5"]) == "ru"
    assert guess_language(["¿qué coche es mejor?"]) == "es"
    assert guess_language(["compare the RAV4 and the CX-5"]) == "en"
