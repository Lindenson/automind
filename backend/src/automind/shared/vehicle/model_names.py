"""Model names as the person wrote them, matched to known models (spec 013 I1: the person's words win).

A model is set only by a match that keeps the person's words: the same name (case, spaces and hyphens aside), the
name written inside the text as whole words, or a Mercedes-style class written another way ("Clase C", "класс С",
"C Klasse" = "C-Class"). Text in Cyrillic cannot be written exactly, so it is transliterated and compared by its
sound — but only when one known model is clearly ahead and no letter code differs ("класс Е" never becomes
"C-Class"). A spelling match of Latin text ("c-class" ≈ "e-class") never sets a model: `suggest_models` offers
it as "did you mean", and the person decides.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from rapidfuzz import fuzz

from automind.shared.text.patterns import whole_word
from automind.shared.vehicle.identity import sound_key, transliterate_ru

SUGGEST_MIN = 72.0  # a spelling score below this is no suggestion
CYRILLIC_MIN = 85.0  # a Cyrillic name matched by its sound: at least this score…
CYRILLIC_MARGIN = 4.0  # …and this far ahead of the next model
MAX_SUGGESTIONS = 3

_CYR = re.compile(r"[а-яё]", re.IGNORECASE)
_LOOKALIKE = str.maketrans("асевкмнорхАСЕВКМНОРХ", "acebkmhopxACEBKMHOPX")  # a Cyrillic letter written as Latin
_CLASS_AFTER = re.compile(r"\b(?:clase|class|klasse|класс|klass)\b\s*-?\s*([a-zа-я]{1,3})\b", re.IGNORECASE)
_CLASS_BEFORE = re.compile(r"\b([a-z]{1,3})\s*-?\s*(?:class|klasse|clase)\b", re.IGNORECASE)
_SEPARATORS = re.compile(r"[-_/]+")
_CYRILLIC_CODE = re.compile(r"\s*[а-яё]{1,3}\s*", re.IGNORECASE)  # "С" of "класс С": a letter code in Cyrillic
_CODE = re.compile(r"\b[a-z]{1,3}\b|\b[a-z]*\d[\w]*\b")  # letter codes and numbered names ("C", "CX-60", "i30")


def match_model(text: str, known: Iterable[str]) -> str | None:
    """The known model the person's text names, or None (then `suggest_models` says what it may have meant).
    Exact, whole words inside the text (the longest wins: "Seal U" over "Seal"), the class form, or — for Cyrillic
    text only — the transliterated sound when one model is clearly ahead."""
    names = sorted(set(known), key=len, reverse=True)
    t = _spaced(text)
    if not t:
        return None
    for k in names:
        if _compact(k) == t.replace(" ", ""):
            return k
    for k in names:
        if whole_word(_spaced(k)).search(t):
            return k
    return _by_sound(text, names) if _CYR.search(text) else None


def suggest_models(text: str, known: Iterable[str], limit: int = MAX_SUGGESTIONS) -> list[str]:
    """Known models spelled or sounding like the text, best first ("did you mean"); never chosen for the person."""
    scored = sorted(((s, k) for k in set(known) if (s := _score(text, k)) >= SUGGEST_MIN), key=lambda x: (-x[0], x[1]))
    return [k for _, k in scored[:limit]]


def _class_form(text: str) -> str:
    """ "Clase C", "класс С", "C Klasse" → "c-class" (the letters of the class in Latin)."""

    def letters(m: re.Match[str]) -> str:
        return f"{m.group(1).translate(_LOOKALIKE).lower()}-class"

    return _CLASS_BEFORE.sub(letters, _CLASS_AFTER.sub(letters, text))


def _spaced(text: str) -> str:
    """Lower case, the class form, words separated by one space (hyphens count as spaces)."""
    return " ".join(_SEPARATORS.sub(" ", _class_form(text).lower()).split())


def _compact(text: str) -> str:
    return _spaced(text).replace(" ", "")


def _score(text: str, model: str) -> float:
    t, k = transliterate_ru(_spaced(text)), _spaced(model)
    tk = sound_key(t)
    return max(fuzz.WRatio(t, k), fuzz.ratio(tk, sound_key(k)) if tk else 0.0)


def _by_sound(text: str, names: list[str]) -> str | None:
    """A Cyrillic name: the known model it sounds like, when clearly ahead and no letter code contradicts it."""
    t = transliterate_ru(_spaced(text.translate(_LOOKALIKE) if _is_code(text) else text))
    scored = sorted(((_score(t, k), k) for k in names), key=lambda x: -x[0])
    if not scored or scored[0][0] < CYRILLIC_MIN:
        return None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < CYRILLIC_MARGIN:
        tied = [k for s, k in scored if scored[0][0] - s < CYRILLIC_MARGIN]
        same_words = [k for k in tied if len(_spaced(k).split()) == len(t.split())]
        if len(same_words) != 1:
            return None
        best = same_words[0]
    else:
        best = scored[0][1]
    return best if _codes_agree(t, best) else None


def _is_code(text: str) -> bool:
    return bool(_CYRILLIC_CODE.fullmatch(text))


def _codes_agree(text: str, model: str) -> bool:
    """Letter codes and numbered names of the model are written in the text too ("CX-60" is not "CX-30")."""
    codes = set(_CODE.findall(_spaced(model))) - {"class"}
    words = {w.lstrip("y") or w for w in _spaced(text).split()} | set(_spaced(text).split())  # "ю" → "yu" ≈ "u"
    return codes <= words
