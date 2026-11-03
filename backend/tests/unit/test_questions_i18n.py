"""Localized question templates (spec 005 R9, FR-023): every kind in en/ru/es, no English leaks, no fallbacks."""

import re

from automind.application.ask import template
from automind.infrastructure.config import load_yaml

Q = {k: v for k, v in load_yaml("questions.yaml").items() if k != "version"}
ENGLISH = re.compile(r"\b(the|which|make and model|did you mean|year or generation|or tell me)\b", re.I)


def test_every_kind_has_three_languages() -> None:
    for kind, t in Q.items():
        for lang in ("en", "ru", "es"):
            assert t.get(lang), (kind, lang)
        for variant in ("rephrase", "bare", "rephrase_bare"):
            if variant in t:
                for lang in ("en", "ru", "es"):
                    assert t[variant].get(lang), (kind, variant, lang)
        if "{options}" in str(t.get("rephrase", {}).get("en", "")):
            assert "rephrase_bare" in t or "{options}" not in t["en"] or kind in ("TOO_MANY_CARS", "TRIM", "GEARBOX"), kind


def test_no_english_in_ru_es() -> None:
    for kind in Q:
        for lang in ("ru", "es"):
            for rephrase in (False, True):
                text = template(Q, kind, lang, rephrase=rephrase, car="BYD Seal U", make="BYD", options="",
                                count=1)  # fmt: skip
                assert not ENGLISH.search(text), (kind, lang, text)


def test_empty_options_never_leave_a_placeholder_or_fallback() -> None:
    for kind in ("UNKNOWN_MODEL", "MAKE_LINEUP", "ENGINE", "USED_AGE"):
        for lang in ("en", "ru", "es"):
            text = template(Q, kind, lang, car="BYD", make="BYD", options="")
            assert "{" not in text and "make and model" not in text and ": ." not in text and "()" not in text, text


def test_options_are_inserted() -> None:
    text = template(Q, "MAKE_LINEUP", "ru", make="BYD", options="Seal U DM-i, Atto 3")
    assert "Seal U DM-i, Atto 3" in text and "BYD" in text


def test_unknown_language_falls_back_to_english() -> None:
    assert template(Q, "CONDITION", "de") == Q["CONDITION"]["en"]
