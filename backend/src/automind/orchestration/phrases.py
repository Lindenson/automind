"""Fixed hub phrases in the supported chat languages (FR-001: replies follow the user's language).

Deterministic text (confirmations, fallbacks) is translated here instead of by a model, so it is
free, instant and testable. Unknown languages fall back to English.
"""

from __future__ import annotations

PHRASES: dict[str, dict[str, str]] = {
    "confirm_variants": {
        "en": "Before I research, please confirm the exact variants:",
        "ru": "Прежде чем искать данные, подтвердите точные модификации:",
        "es": "Antes de investigar, confirma las versiones exactas:",
    },
    "confirm_cost": {
        "en": "Researching {cars} at {depth} depth costs about €{eur}.{cap} Run it?",
        "ru": "Исследование {cars} (глубина: {depth}) обойдётся примерно в €{eur}.{cap} Запустить?",
        "es": "Investigar {cars} (profundidad: {depth}) cuesta unos {eur} €.{cap} ¿Lo ejecuto?",
    },
    "over_cap": {
        "en": " It may stop at the €{cap} per-turn cap.",
        "ru": " Работа может остановиться на лимите €{cap} за ход.",
        "es": " Puede detenerse en el límite de {cap} € por turno.",
    },
    "rephrase": {
        "en": "Sorry, I could not map that to the cars we are discussing. Could you rephrase it?",
        "ru": "Не понял, к какой из машин это относится. Можете сформулировать иначе?",
        "es": "No he podido relacionarlo con los coches que comentamos. ¿Puedes reformularlo?",
    },
    "which_car": {
        "en": "Which of the cars do you mean? Please name it.",
        "ru": "Какую из машин вы имеете в виду? Назовите её, пожалуйста.",
        "es": "¿A cuál de los coches te refieres? Dime cuál, por favor.",
    },
    "variants_skipped": {
        "en": "OK — tell me which exact variants you mean (generation, year or engine).",
        "ru": "Хорошо — напишите, какие именно модификации вы имеете в виду (поколение, год или двигатель).",
        "es": "De acuerdo: dime qué versiones exactas quieres (generación, año o motor).",
    },
}


def t(key: str, language: str | None, **kw: object) -> str:
    table = PHRASES[key]
    text = table.get((language or "en")[:2].lower(), table["en"])
    return text.format(**kw) if kw else text
