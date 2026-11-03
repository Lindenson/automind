"""Fixed hub phrases in the supported chat languages (FR-001: replies follow the user's language).

Deterministic text (confirmations, fallbacks) is translated here instead of by a model, so it is
free, instant and testable. Unknown languages fall back to English.
"""

from __future__ import annotations

PHRASES: dict[str, dict[str, str]] = {
    "profile_KM_PER_YEAR": {
        "en": "To sharpen this: how many km a year do you drive? (I assumed {km} km.)",
        "ru": "Чтобы уточнить: сколько километров в год вы проезжаете? (Я принял {km} км.)",
        "es": "Para afinar: ¿cuántos km al año conduces? (He supuesto {km} km.)",
    },
    "profile_FAMILY_SIZE": {
        "en": "To sharpen this: who usually travels in the car?",
        "ru": "Чтобы уточнить: кто обычно ездит в машине?",
        "es": "Para afinar: ¿quién suele viajar en el coche?",
    },
    "family_single": {"en": "Mostly just me", "ru": "В основном я один", "es": "Sobre todo yo solo"},
    "family_couple": {"en": "The two of us", "ru": "Нас двое", "es": "Somos dos"},
    "family_kids": {"en": "A family with children", "ru": "Семья с детьми", "es": "Una familia con niños"},
    "critique_researched": {
        "en": "I went back to the sources for what was missing ({areas}) and rebuilt the report.",
        "ru": "Я заново поискал недостающее ({areas}) и пересобрал отчёт.",
        "es": "He vuelto a buscar lo que faltaba ({areas}) y he rehecho el informe.",
    },
    "critique_reworked": {
        "en": "Nothing new was found in the sources, so I reworked the report around what you asked: {what}.",
        "ru": "Новых данных в источниках нет, поэтому я переработал отчёт с упором на то, что вы просили: {what}.",
        "es": "No hay datos nuevos en las fuentes, así que he rehecho el informe centrado en lo que pediste: {what}.",
    },
    "not_understood": {
        "en": "I did not understand “{answer}” for {car}.",
        "ru": "Я не понял ответ «{answer}» для {car}.",
        "es": "No he entendido «{answer}» para {car}.",
    },
    "unknown_model": {
        "en": "I don't know the model “{car}”.",
        "ru": "Я не знаю модель «{car}».",
        "es": "No conozco el modelo «{car}».",
    },
    "did_you_mean": {
        "en": "Did you mean: {options}?",
        "ru": "Возможно, вы имели в виду: {options}?",
        "es": "¿Quizás quisiste decir: {options}?",
    },
    "choose_for_me": {"en": "Choose for me", "ru": "Выбери сам", "es": "Elige tú"},
    "remove_car": {"en": "Remove {car}", "ru": "Убрать {car}", "es": "Quitar {car}"},
    "compared_at_level": {
        "en": "All cars are compared at the {level} level{why}.",
        "ru": "Все машины сравниваются в {level} комплектации{why}.",
        "es": "Todos los coches se comparan en el nivel {level}{why}.",
    },
    "level_BASE": {"en": "base", "ru": "базовой", "es": "base"},
    "level_MID": {"en": "mid", "ru": "средней", "es": "medio"},
    "level_TOP": {"en": "top", "ru": "топовой", "es": "alto"},
    "level_why_default": {
        "en": " (the cheapest version on sale; name a version to change it)",
        "ru": " (самая дешёвая версия в продаже; назовите версию, чтобы изменить)",
        "es": " (la versión más barata a la venta; nombra una versión para cambiarlo)",
    },
    "level_why_user": {
        "en": " (the level of the version you named)",
        "ru": " (уровень названной вами версии)",
        "es": " (el nivel de la versión que nombraste)",
    },
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
    # spec 005: intake chips and notices
    "cond_new": {"en": "New", "ru": "Новые", "es": "Nuevos"},
    "cond_used": {"en": "Used", "ru": "Подержанные", "es": "De segunda mano"},
    "yes": {"en": "Yes", "ru": "Да", "es": "Sí"},
    "no_other": {"en": "No, another one", "ru": "Нет, другую", "es": "No, otro"},
    "changed_car": {"en": "{before} → {after}", "ru": "{before} → {after}", "es": "{before} → {after}"},
    "page_taken": {
        "en": "From the page I took: {what}.",
        "ru": "Со страницы я взял: {what}.",
        "es": "De la página he tomado: {what}.",
    },
    "page_refused": {
        "en": "I do not read classified-ads sites ({site}). Please write the car in words.",
        "ru": "Сайты объявлений ({site}) я не читаю. Напишите, пожалуйста, машину словами.",
        "es": "No leo portales de anuncios ({site}). Escribe el coche con palabras, por favor.",
    },
    "suggested": {"en": "suggestion", "ru": "предложение", "es": "sugerencia"},
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


_CHOOSE = (
    "choose for me", "you choose", "any", "whatever", "doesn't matter", "dont care", "don't care",
    "любой", "любая", "любую", "любое", "выбери сам", "выбери ты", "на твой выбор", "на ваш выбор", "всё равно",
    "все равно", "неважно", "не важно", "cualquiera", "elige tú", "elige tu", "me da igual", "da igual",
)  # fmt: skip


def choose_for_me(text: str | None) -> bool:
    """ "Any" / "choose for me": the hub takes the base version (spec 004 FR-029, US8 scenario 6)."""
    t = " ".join((text or "").lower().replace("!", " ").replace(".", " ").replace(",", " ").split())
    return bool(t) and len(t) <= 40 and any(t == c or t.startswith(c + " ") or t.endswith(" " + c) for c in _CHOOSE)


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


def guess_language(texts: list[str]) -> str:
    """Language of the conversation from the user's own words (for button requests without text)."""
    t = " ".join(texts[-4:]).lower()
    if any("а" <= ch <= "я" or ch == "ё" for ch in t):
        return "ru"
    if any(ch in t for ch in "ñ¿¡áéíóú") or any(w in f" {t} " for w in (" el ", " los ", " coche", " qué ")):
        return "es"
    return "en"
