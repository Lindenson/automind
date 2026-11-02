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
    "limit_reached": {
        "en": "I paused the research at the {reasons} limit: €{eur} and {calls} AI calls so far, {minutes} min, "
        "{left} task(s) left. Continue (up to €{more} for this turn) or answer with what I have?",
        "ru": "Я приостановил исследование: достигнут лимит ({reasons}). Потрачено €{eur}, {calls} вызовов ИИ, "
        "{minutes} мин; осталось заданий: {left}. Продолжить (до €{more} за этот ход) или ответить по тому, "
        "что уже собрано?",
        "es": "He pausado la investigación al llegar al límite ({reasons}): {eur} € y {calls} llamadas de IA, "
        "{minutes} min; quedan {left} tarea(s). ¿Continúo (hasta {more} € en este turno) o respondo con lo que tengo?",
    },
    "limit_calls": {"en": "AI calls", "ru": "вызовы ИИ", "es": "llamadas de IA"},
    "limit_cost": {"en": "cost", "ru": "стоимость", "es": "coste"},
    "limit_cost_cap": {"en": "cost", "ru": "стоимость", "es": "coste"},
    "limit_llm_calls": {"en": "AI calls", "ru": "вызовы ИИ", "es": "llamadas de IA"},
    "limit_time": {"en": "time", "ru": "время", "es": "tiempo"},
    "limit_continue": {"en": "Continue research", "ru": "Продолжить исследование", "es": "Seguir investigando"},
    "limit_stop": {"en": "Answer with what you have", "ru": "Ответить по собранному", "es": "Responder con lo que hay"},
    "feasibility_intro": {
        "en": "Before the full comparison — this does not fully fit what you asked for:",
        "ru": "Прежде чем сравнивать подробно: это не совсем укладывается в ваши условия:",
        "es": "Antes de la comparación completa: esto no encaja del todo con lo que pides:",
    },
    "feasibility_question": {
        "en": "How do you want to continue?",
        "ru": "Как продолжим?",
        "es": "¿Cómo seguimos?",
    },
    "feasibility_report": {
        "en": "Show the report anyway",
        "ru": "Всё равно показать отчёт",
        "es": "Mostrar el informe igualmente",
    },
    "feasibility_used": {"en": "Look at used ones", "ru": "Посмотреть б/у", "es": "Ver de segunda mano"},
    "feasibility_alternatives": {
        "en": "Suggest cars that fit",
        "ru": "Предложить подходящие машины",
        "es": "Sugerir coches que encajen",
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


_YES = ("continue", "go on", "go ahead", "keep going", "yes", "ok", "okay", "sure", "proceed", "run",
        "да", "давай", "продолж", "дальше", "ок", "поехали", "запуск", "sí", "si", "sigue", "continúa", "continua",
        "adelante", "vale")  # fmt: skip
_NO = ("stop", "no", "enough", "answer", "nein", "нет", "стоп", "хватит", "достаточно", "отвечай", "ответь",
       "basta", "para", "responde")  # fmt: skip


def yes_or_no(text: str | None) -> str | None:
    """A short typed answer to a confirmation: "yes", "no", or None (not a plain yes/no: a new message)."""
    t = " ".join((text or "").lower().replace("!", " ").replace(".", " ").replace(",", " ").split())
    if not t or len(t) > 40:
        return None
    words = t.split()
    if any(t == n or words[0] == n for n in _NO):
        return "no"
    if any(t.startswith(y) or words[0].startswith(y) for y in _YES):
        return "yes"
    return None
