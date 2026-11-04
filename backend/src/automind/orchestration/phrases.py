"""Fixed hub phrases in the supported chat languages (FR-001: replies follow the user's language).

Deterministic text (confirmations, fallbacks) is translated here instead of by a model, so it is
free, instant and testable. Unknown languages fall back to English.
"""

from __future__ import annotations

import re

PHRASES: dict[str, dict[str, str]] = {
    # runner (reviewer 2026-11-03: these were English in every chat)
    "run_limit": {
        "en": 'I stopped here because a limit was reached ({what}). What was found is saved: say "continue" '
        "and I will go on from it.",
        "ru": "Я остановился: достигнут лимит ({what}). Найденное сохранено — напишите «продолжай», и я продолжу "
        "с этого места.",
        "es": "Me he detenido porque se alcanzó un límite ({what}). Lo encontrado está guardado: di «sigue» y "
        "continúo desde aquí.",
    },
    "run_timeout": {
        "en": 'This took too long, so I stopped. The data gathered so far is saved: say "continue" and I will '
        "write the report from it.",
        "ru": "Это заняло слишком много времени, и я остановился. Собранные данные сохранены — напишите "
        "«продолжай», и я соберу отчёт из них.",
        "es": "Esto ha tardado demasiado y me he detenido. Los datos reunidos están guardados: di «sigue» y "
        "redacto el informe con ellos.",
    },
    "run_timeout_saved": {
        "en": "This took too long, so I stopped searching. I am writing the report from the data already found.",
        "ru": "Поиск занял слишком много времени, и я его остановил. Собираю отчёт из уже найденных данных.",
        "es": "La búsqueda tardó demasiado y la detuve. Preparo el informe con los datos ya encontrados.",
    },
    "run_provider_down": {
        "en": "The AI service is not answering right now (I tried twice). Nothing is lost: the case and the data "
        "found are saved. Send the message again in a minute.",
        "ru": "Сервис ИИ сейчас не отвечает (я попробовал дважды). Ничего не потеряно: кейс и найденные данные "
        "сохранены. Отправьте сообщение ещё раз через минуту.",
        "es": "El servicio de IA no responde ahora (lo intenté dos veces). No se pierde nada: el caso y los datos "
        "están guardados. Envía el mensaje de nuevo en un minuto.",
    },
    "run_loop": {
        "en": "I went round in circles on this request and stopped. Please rephrase what you need, or say what "
        "to change in the cars or the profile.",
        "ru": "Я зациклился на этом запросе и остановился. Переформулируйте, пожалуйста, что нужно, или скажите, "
        "что поменять в машинах или профиле.",
        "es": "Me he quedado dando vueltas con esta petición y me he detenido. Reformula lo que necesitas o dime "
        "qué cambiar en los coches o el perfil.",
    },
    "run_no_answer": {
        "en": "Sorry, I could not produce an answer.",
        "ru": "Извините, не получилось сформировать ответ.",
        "es": "Lo siento, no he podido generar una respuesta.",
    },
    "run_limits_notice": {
        "en": "Limit reached this turn: {what}",
        "ru": "На этом ходе достигнут лимит: {what}",
        "es": "Límite alcanzado en este turno: {what}",
    },
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
    "profile_PERSONA": {
        "en": "To sharpen this: what matters most to you in a car? The answer changes the winner here.",
        "ru": "Чтобы уточнить: что для вас главное в машине? От ответа здесь зависит победитель.",
        "es": "Para afinar: ¿qué es lo más importante para ti en un coche? La respuesta cambia el ganador.",
    },
    "profile_HOME_CHARGING": {
        "en": "To sharpen this: can you charge at home or at work? The answer changes which car is cheaper to run.",
        "ru": "Чтобы уточнить: можете ли вы заряжать машину дома или на работе? От ответа зависит, какая дешевле "
        "в содержании.",
        "es": "Para afinar: ¿puedes cargar en casa o en el trabajo? La respuesta cambia qué coche sale más barato.",
    },
    "charge_YES": {"en": "Yes, I can charge at home", "ru": "Да, могу заряжать дома", "es": "Sí, puedo cargar en casa"},
    "charge_WORK": {"en": "I charge at work", "ru": "Заряжаю на работе", "es": "Cargo en el trabajo"},
    "charge_NO": {"en": "No, street parking", "ru": "Нет, паркуюсь на улице", "es": "No, aparco en la calle"},
    "profile_OWNERSHIP_YEARS": {
        "en": "To sharpen this: how many years will you keep the car? (I assumed {years}.)",
        "ru": "Чтобы уточнить: сколько лет вы будете владеть машиной? (Я принял {years}.)",
        "es": "Para afinar: ¿cuántos años tendrás el coche? (He supuesto {years}.)",
    },
    "persona_PERFORMANCE": {
        "en": "Driving and performance",
        "ru": "Динамика и удовольствие от вождения",
        "es": "Conducción y prestaciones",
    },
    "persona_BUYER": {
        "en": "Family, practicality and cost",
        "ru": "Семья, практичность и расходы",
        "es": "Familia, practicidad y coste",
    },
    "persona_EXPERT": {
        "en": "Engineering and technology",
        "ru": "Техника и инженерия",
        "es": "Ingeniería y tecnología",
    },
    "years_3": {"en": "About 3 years", "ru": "Около 3 лет", "es": "Unos 3 años"},
    "years_5": {"en": "About 5 years", "ru": "Около 5 лет", "es": "Unos 5 años"},
    "years_8": {"en": "About 8 years", "ru": "Около 8 лет", "es": "Unos 8 años"},
    "years_12": {"en": "10 years or more", "ru": "10 лет и больше", "es": "10 años o más"},
    "family_single": {"en": "Mostly just me", "ru": "В основном я один", "es": "Sobre todo yo solo"},
    "family_couple": {"en": "The two of us", "ru": "Нас двое", "es": "Somos dos"},
    "family_kids": {"en": "A family with children", "ru": "Семья с детьми", "es": "Una familia con niños"},
    "style_CALM": {"en": "Calm, relaxed driving", "ru": "Спокойная езда", "es": "Conducción tranquila"},
    "style_MIXED": {"en": "A bit of everything", "ru": "По-разному", "es": "Un poco de todo"},
    "style_SPORTY": {
        "en": "Sporty, I like it fast",
        "ru": "Спортивно, люблю быстро",
        "es": "Deportiva, me gusta rápido",
    },
    "confirm_yes": {"en": "Yes, that's right: {what}", "ru": "Да, верно: {what}", "es": "Sí, es así: {what}"},
    "confirm_no": {"en": "No, that's not me", "ru": "Нет, это не про меня", "es": "No, no es mi caso"},
    "confirm_q": {
        "en": "I took this from your words: {what}. It decides the winner here — is it right?",
        "ru": "Я понял это из ваших слов: {what}. Здесь от этого зависит победитель — верно?",
        "es": "Lo he deducido de tus palabras: {what}. Aquí decide el ganador — ¿es correcto?",
    },
    "assume_note": {
        "en": "This assumes: {what} (from your words “{ev}”, not confirmed). Without it {other}.",
        "ru": "Это при допущении: {what} (по вашим словам «{ev}», не подтверждено). Без него {other}.",
        "es": "Esto supone: {what} (por tus palabras «{ev}», sin confirmar). Sin ello {other}.",
    },
    "other_wins": {"en": "the {car} would win", "ru": "победил бы {car}", "es": "ganaría el {car}"},
    "other_tie": {"en": "it would be too close to call", "ru": "была бы ничья", "es": "estarían igualados"},
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
    "gb_automatic": {"en": "Automatic", "ru": "Автомат", "es": "Automático"},
    "gb_manual": {"en": "Manual", "ru": "Механика", "es": "Manual"},
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
    "limit_daily": {"en": "daily spend", "ru": "дневные расходы", "es": "gasto diario"},
    "limit_daily_note": {
        "en": " Today all chats have spent €{spent} of the €{cap} daily cap.",
        "ru": " Сегодня все чаты вместе потратили €{spent} из дневного лимита €{cap}.",
        "es": " Hoy todos los chats han gastado {spent} € del límite diario de {cap} €.",
    },
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
    "intake_card": {
        "en": "Please check what I understood and confirm — then I start the research (≈ €{eur}).",
        "ru": "Проверьте, что я понял, и подтвердите — после этого начну исследование (≈ €{eur}).",
        "es": "Comprueba lo que he entendido y confirma; después empiezo la investigación (≈ {eur} €).",
    },
    "card_yes": {"en": "Yes, research", "ru": "Да, исследовать", "es": "Sí, investigar"},
    "card_stop": {"en": "Not now", "ru": "Пока не надо", "es": "Ahora no"},
    "suggested": {"en": "suggestion", "ru": "предложение", "es": "sugerencia"},
    "cand_intro": {
        "en": "You did not name a car, so I picked candidates for your need and budget:",
        "ru": "Вы не назвали машину, поэтому я подобрал кандидатов под вашу задачу и бюджет:",
        "es": "No nombraste un coche, así que elegí candidatos para tu necesidad y presupuesto:",
    },
    "cand_price": {"en": "from €{eur}", "ru": "от {eur} €", "es": "desde {eur} €"},
    "cand_price_check": {"en": "price to check", "ru": "цену нужно уточнить", "es": "precio por confirmar"},
    "cand_fits": {
        "en": "fits the class and the budget",
        "ru": "подходит по классу и бюджету",
        "es": "encaja en la clase y el presupuesto",
    },
    "why_family_body": {"en": "family-size body", "ru": "семейный кузов", "es": "carrocería familiar"},
    "why_phev_low_running_cost": {
        "en": "plug-in hybrid: low running cost at your km",
        "ru": "плагин-гибрид: дёшево ездить при вашем пробеге",
        "es": "híbrido enchufable: gasto bajo con tus km",
    },
    "why_bev_low_running_cost": {
        "en": "electric: low running cost",
        "ru": "электро: дёшево в эксплуатации",
        "es": "eléctrico: gasto bajo",
    },
    "why_hybrid_low_running_cost": {
        "en": "hybrid: low consumption",
        "ru": "гибрид: низкий расход",
        "es": "híbrido: consumo bajo",
    },
    "why_price_close": {
        "en": "price close to the other car",
        "ru": "цена близка к другой машине",
        "es": "precio parecido al otro coche",
    },
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
    "new_generation": {
        "en": "{car}: a new generation, on sale since {year}. It has no reliability history yet, so the "
        "comparison leaves reliability out instead of guessing.",
        "ru": "{car}: новое поколение, в продаже с {year} года. Статистики надёжности у него ещё нет, поэтому "
        "сравнение идёт без надёжности, а не на догадках.",
        "es": "{car}: generación nueva, a la venta desde {year}. Aún no tiene historial de fiabilidad, así que la "
        "comparación la deja fuera en lugar de suponer.",
    },
    "energy_missing": {
        "en": "{car}: energy cost cannot be computed — missing: {missing}. Running cost is not compared.",
        "ru": "{car}: стоимость энергии не посчитать — нет данных: {missing}. Расходы на владение не сравниваются.",
        "es": "{car}: no se puede calcular el coste de energía — falta: {missing}. No se comparan los costes de uso.",
    },
    "short_data": {
        "en": "{car}: insufficient data for {area} (minimum evidence not reached)",
        "ru": "{car}: мало данных — {area} (не набран минимум источников)",
        "es": "{car}: datos insuficientes — {area} (no se alcanzó el mínimo de fuentes)",
    },
    "job_incomplete": {
        "en": "{car}: {area} research incomplete ({error})",
        "ru": "{car}: поиск — {area} не завершён ({error})",
        "es": "{car}: búsqueda de {area} incompleta ({error})",
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


ENERGY_INPUTS: dict[str, dict[str, str]] = {  # the inputs domain/energy.py names when a cost cannot be computed
    "fuel consumption with an empty battery": {"en": "fuel consumption with an empty battery",
                                               "ru": "расход топлива с разряженной батареей",
                                               "es": "consumo con la batería descargada"},
    "electric consumption (kWh/100 km)": {"en": "electric consumption (kWh/100 km)",
                                          "ru": "расход электричества (кВт·ч/100 км)",
                                          "es": "consumo eléctrico (kWh/100 km)"},
    "electric range": {"en": "electric range", "ru": "запас хода на электричестве", "es": "autonomía eléctrica"},
    "fuel consumption": {"en": "fuel consumption", "ru": "расход топлива", "es": "consumo de combustible"},
}  # fmt: skip


def energy_input(name: str, language: str | None) -> str:
    return ENERGY_INPUTS.get(name, {}).get((language or "en")[:2].lower(), name)


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


# spec 007 F: a gearbox named in one word (a tapped chip or typed) answers the gearbox question by code
GEARBOX_WORDS: dict[str, str] = {
    "automatic": "automatic", "auto": "automatic", "automatic gearbox": "automatic", "автомат": "automatic",
    "автомат.": "automatic", "акпп": "automatic", "автоматическая": "automatic", "автоматическая коробка": "automatic",
    "робот": "automatic", "automático": "automatic", "automatico": "automatic", "cambio automático": "automatic",
    "manual": "manual", "manual gearbox": "manual", "механика": "manual", "мкпп": "manual", "ручка": "manual",
    "механическая": "manual", "механическая коробка": "manual", "cambio manual": "manual",
}  # fmt: skip


def choose_for_me(text: str | None) -> bool:
    """ "Any" / "choose for me": the hub takes the base version (spec 004 FR-029, US8 scenario 6)."""
    t = " ".join((text or "").lower().replace("!", " ").replace(".", " ").replace(",", " ").split())
    return bool(t) and len(t) <= 40 and any(t == c or t.startswith(c + " ") or t.endswith(" " + c) for c in _CHOOSE)


_GO = ("вперед", "вперёд", "давай", "продолжай", "дальше", "к сравнению", "сравнивай", "go ahead", "go on",
       "continue", "proceed", "adelante", "sigue", "continúa", "continua", "compara")  # fmt: skip


def go_ahead(text: str | None) -> bool:
    """ "Go ahead" / "вперёд к сравнению": a short reply that asks to move on (taken as "choose for me" by a
    pending identity question, chat 9b5c0b0c)."""
    t = " ".join((text or "").lower().replace("!", " ").replace(".", " ").replace(",", " ").split())
    return bool(t) and len(t) <= 40 and any(re.search(rf"(?<!\w){re.escape(g)}(?!\w)", t) for g in _GO)


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


def stable_language(detected: str | None, current: str, earlier: list[str]) -> str | None:
    """The conversation language with hysteresis (reviewer 2026-11-03): one message with an English model name
    or a quote must not switch a Russian chat. The language changes only when the new message is a sentence
    (4+ words) that is itself written in the detected language."""
    if not earlier or not detected:
        return detected
    prev = guess_language(earlier)
    if detected == prev:
        return detected
    words = len(current.split())
    if words >= 4 and (guess_language([current]) == detected or detected not in ("en", "ru", "es")):
        return detected
    return prev
