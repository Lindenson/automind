# Аудит покрытия: исходная спека понимания → спеки 013 + 014

Дата: 2026-11-26. Только чтение; код проверялся grep-ом лишь там, где нужно понять, сделано ли требование.

Источник: `specs/013-dialogue-quality/understanding-spec.md` (§1–§10; §11 — только краткое резюме в конце файла).
Наши документы: `013/spec.md` (далее **13s**), `013/tasks.md` (**13t**), `014/spec.md` (**14s**), `014/tasks.md` (**14t**).

Статусы: **Covered** — требование есть в спеке и в задаче; **Partial** — есть, но неполно или только по имени
(«как в understanding spec») без закрепления деталей; **Missing** — нет ни в спеке, ни в задачах;
**Contradicted / Различие** — наши документы говорят иное (цитаты обеих сторон).

## 0. Важные общие замечания

| # | Замечание | Последствие |
|---|---|---|
| G1 | `understanding-spec.md` **не закоммичен** (`git status`: `?? specs/013-dialogue-quality/understanding-spec.md`, `git log` по файлу пуст). 13s §D1 и 13t T030/T005 ссылаются на него («as the understanding spec §4»). | Пока файл не в репозитории, все детали схем и правил, закреплённые «по ссылке», формально не закреплены нигде. Закоммитить файл — первое исправление. |
| G2 | 13t, примечание после S0: «T004–T006 wait for the understanding spec's §4 … not in the repo». Теперь §4 есть. | Обновить примечание, разблокировать T004–T006. |
| G3 | 13t T005: «the old label mapping (spec §D1 table)». В 13s §D1 таблицы нет — только фраза «Mapping of old labels as in the understanding spec §4». | Висячая ссылка; заменить на «understanding-spec.md §4, таблица соответствия». |
| G4 | Оригинальный текст §11 в репозитории отсутствует (есть только резюме в 6 строк). | Пункты §11 можно сверить только с резюме; детальная сверка 11.1–11.5 невозможна. Рекомендуется сохранить оригинал §11 дословно (в конце understanding-spec.md или в 014). |
| G5 | Таблица шести этапов миграции в источнике отсутствует; номера этапов восстанавливаются по упоминаниям (§9, §10, §11.6). | Сопоставление этапов с S0–S7 (раздел 9.1 ниже) — вывод, а не цитата. |

## 1. Примеры промахов (§1)

Все 11 примеров перечислены в 13s §B4; T004 требует «every example of spec §B4» в эталонном наборе; T045 «all §B4
examples green»; приёмка 13s §E.

| # | Пример | Статус | Где закрывается | Состояние кода |
|---|---|---|---|---|
| 1.1 | «да, но дизель» на карточку | Covered | 13s §B4; T012 (S1, карточка), T042/T045 (S4); g16 | S1: на карточке текст больше не идёт в yes_or_no (`domain/intake/card_choice.py`: «typed words are never read here»). Вне карточки `picked_option` по тексту ещё жив (`interpretation/service.py:87`) — до S4. |
| 1.2 | «давно хотел дизель» → «да» | Covered | §B4; T042/T045 | `picked_option` → `words.yes_or_no(text)` (`stages/picked_option.py:14`) ещё активен. |
| 1.3 | «дайте подумать» → «да» | Covered | §B4; T042/T045 | то же. |
| 1.4 | «para mi familia» → «нет» | Covered | §B4; T042/T045 | то же. |
| 1.5 | «answer me about fuel» → «нет» | Covered | §B4; T042/T045 | то же. |
| 1.6 | «все равно хочу дизель» → «выбери сам» | Covered | §B4; T040 (apply «never rewrites intent»), T045 | `service.py:110` `choose_for_me(text)` переписывает метку — до S4. |
| 1.7 | «do you have any…» → «выбери сам» | Covered | §B4; T042/T045 | до S4. |
| 1.8 | «давай сравним с BMW» при открытом вопросе | Covered | §B4; g17 (T001), T045 | до S4. |
| 1.9 | «а что такое DSG?» при вопросе о коробке | Covered | §B4; g17; T040/T041 (ANSWER_AND_REASK) | `service.py:111` `general_question → compare` — до S4. |
| 1.10 | «да, и добавь Hyundai» | Covered | §B4; T004 (two-intent), T041 | до S4. |
| 1.11 | «переформулируйте» → английский | Covered | §B4; T032 `language_hysteresis`, T040 («never "en"»), 14t T121 | `Reading(None, None, ask="rephrase")` (`service.py:92`) и `PER_TURN_RESET "language": "en"` (`dialog/state.py:74`) ещё на месте. |

## 2. Цели и не-цели (§2)

| # | Требование | Статус | Где / что не так |
|---|---|---|---|
| 2.G1 | Одна точка понимания текста, включая ответ на подтверждение | Covered | 13s §C4; T032, T042 |
| 2.G2 | Кнопки шлют id варианта | Covered | 13s §C4; T013 — **сделано** в S1 (`domain/intake/option_ids.py`, `card_choice.py`, фронт `store/chat.ts:555` `option_id`) |
| 2.G3 | Несколько намерений: ответ, цели, факты — отдельными полями | Covered | §D1 схемы; T030, T041 |
| 2.G4 | Вопрос пользователя не теряется: ответ + повтор вопроса бота | Covered | §D1 `ANSWER_AND_REASK`; T041 |
| 2.G5 | Политика начинает с цели и **объясняет, чего не хватает** | Partial | T041: «reason names the goal and the rule» — это `Action.reason` (внутреннее). Пользовательский вопрос с причиной («Чтобы сравнить, нужен год Prado», §5.4.2) нигде не закреплён. |
| 2.G6 | Одна запись на ход | Covered | 13s §C6, §D5; T033, T035 |
| 2.G7 | Изменения промпта/правил проверяются эталоном до выката | Covered | 13s §C7, §G2; T005, T006 |
| 2.N1 | Действие выбирает код, не модель | Covered | 13s non-goals |
| 2.N2 | CaseDelta и domain apply() не меняются | Covered (с оговоркой) | 13s non-goals. Оговорка: 13t T020 добавляет `CaseCar.identity_rejected`, T031 — `Pending.id/options` (требует сам источник), T071 — новый `Fuel` EREV. CaseDelta и правила apply() формально не трогаются; `rejections` идут отдельным полем Understanding, не в CaseDelta — противоречия нет. |
| 2.N3 | Не трогаем идентификацию, исследование, отчёт, guard | Covered / снято владельцем | Идентификация снята владельцем (13s, заголовок). Исследование/отчёт/guard: 13s non-goals «untouched». Касания: T043 (читатели request_kind в research/report — требует сам источник §3), S6 кнопки на лимите, 14t T112 (порядок persist в `report_node`, без смены поведения). Противоречий нет. |
| 2.N4 | Проверки ответа модели кодом остаются | Covered | 13s non-goals; T032 (перенос проверок) |

## 3. Восемь мест понимания и семь читателей (§3)

| # | Место → в новой схеме | Статус | Где / что не так |
|---|---|---|---|
| 3.1 | `read`, ветка `car_edit` → UiAction(edit_car) **с точными ошибками** | Partial | T030 только объявляет `UiAction`. Нет задачи «car_edit → UiAction(edit_car)» и нет требования точных ошибок вместо «какую машину?» (`service.py:131-133`: любая ошибка → `ask="which_car"`). |
| 3.2 | `read`, ветка `preset` → UiAction, отдельный тип | Partial | S1 добавил preset `pick` + `option_id` (T013). Остальные preset (`research_more`, `rescore`) → `UiAction(research_more/panel_edit)` — нет задачи. 14s §D1 упоминает «ui_action / preset» в секции `input`. |
| 3.3 | `picked_option` удаляется; кнопки шлют option_id, текст в модель | Partial | Кнопки — сделано (T013). Удаление стадии `picked_option` по тексту (`service.py:87,127`, `stages/picked_option.py`) явно ни в одной задаче не названо; T042 говорит только о списках слов в `phrases.py`. |
| 3.4 | `interpret()` → Understander; проверки остаются; язык не теряется | Covered | T032; T040 |
| 3.5 | `apply`: choose_for_me-переписывание, general_question→compare, страховочная сеть → в IntentResolver | Covered | T040 («never rewrites intent»), T032 (`cars_safety_net`, `no_goal_with_pending`). Три удаляемых решения поимённо не перечислены — рекомендуется назвать в T040. |
| 3.6 | `pending_answered` → по `answer_to_pending`; не отвечено → вопрос остаётся | Partial | T040: «applies case_changes + the pending answer». Нет требования «не отвечено → pending остаётся» и правила снятия при смене темы (§5.3). |
| 3.7 | `confirm.apply_intake` (и др. apply_*): свой разбор; дубль `_card_edit` | Partial | T012 — **сделано** (S1, `card_choice.py`); T042 — PendingAnswer в apply_*. Дубль `_card_edit` (`dialog/nodes/confirm.py:370`) не упомянут ни в одной задаче. |
| 3.8 | `research.apply_limit`: свой yes_or_no | Covered | T042 (`research.apply_limit`). Код: `nodes/research.py:108` `yes_or_no` ещё на месте — до S4. |
| 3.R | 7 читателей `request_kind`: policy (answer/general/limits), understand.py, research.py, report_writer, report_followup, tracing, метрики | Covered | T043 перечисляет все семь дословно. 14s §B2 подтверждает места (`report_writer.py:32`, `report_followup.py:54`, `research.py:143`, `understand.py:91,106`, `tracing.py:102`). |

## 4. Модель данных (§4)

### 4.1 Поля и схемы

Общее: 13s §D1 и 13t T030 называют схемы и ссылаются на understanding spec §4; ни одно значение Literal в 013 не
повторено. Пока файл-источник не закоммичен (G1), все строки ниже «по имени» — Partial.

| # | Элемент схемы | Статус | Где / что не так |
|---|---|---|---|
| 4.1 | Таблица «вопрос → поле» (answer_to_pending, goals, reaction, case_changes, language) | Covered | §D1, T030 |
| 4.2 | `PendingAnswer.pending_id` (сверка с case.pending.id) | Partial | только по имени (T030); сверка — правило `stale_pending` (T032) |
| 4.3 | `PendingAnswer.kind` ∈ {option, value, yes, no, choose_for_me} | Partial | значения не закреплены нигде в 013 |
| 4.4 | `PendingAnswer.option_id` «только из предложенных» | Partial | проверка в T032 («option_id exist») — Covered; само поле — по имени |
| 4.5 | `PendingAnswer.evidence` | Partial | по имени; используется в D1-добавлении (complaint без ответа в evidence) |
| 4.6 | `GoalKind` ∈ {compare, single, follow_up, change_priorities, research_more, ask_general, critique} (+ `stop` у нас) | Partial | в 013 закреплено только «+ stop»; базовые 7 значений — по ссылке |
| 4.7 | `Goal.focus_cars` (car#N), `focus_areas`, `question` (для follow_up/ask_general) | Partial | по имени |
| 4.8 | `Reaction` ∈ {thanks, complaint, correction, rephrase} | Partial | в 013 упомянут только `complaint` (D1, D3) |
| 4.9 | `Understanding`: language, answer_to_pending, goals (**порядок = порядок в сообщении**), reaction, case_changes, persona_evidence, constraints_evidence (+ rejections у нас) | Partial | поля по ссылке; правило «порядок целей = порядок в сообщении» нигде не повторено (важно для §5.4.3) |
| 4.10 | `UiAction.kind` ∈ {pick_option, confirm, decline, choose_for_me, edit_car, research_more, panel_edit} (+ complain, quit у нас) | Partial | в 013 закреплены только добавленные `complain|quit` (D3, T060). Реализация S1 не использует UiAction: id-схема `q:/gb:/condition:/remove:/choose/yes:/no:` (`option_ids.py`) и `card_choice` (`yes/stop/skip/option:/remove:/edit_field`). Нет задачи, сводящей их к UiAction. |
| 4.11 | `UiAction` поля: pending_id, option_id, car_key, field, value, focus_cars, focus_areas | Partial | по имени. Факт: чипы S1 **не шлют pending_id** (фронт шлёт только `option_id`, `protocol.ts:1097`) — правилу `stale_pending` для кнопок нечем сверять. |
| 4.12 | `Override`: rule, field, before, after, why | Partial | по имени (T032 «each writes an Override»); поля перечислены в T035/§D5 только как «overrides» |
| 4.13 | `Intent.source` ∈ {text, ui, system} | Partial | нигде в 013 не упомянут; нет задачи, кто ставит `system` (report_saved, см. 4.M12) |
| 4.14 | `Intent`: language, answer_to_pending, goals, reaction, case_changes, overrides (пусто = принято как есть) | Partial | по имени (T030) |
| 4.15 | Требование к Pending: `id` + `options[{id,label}]`; **те же id в кнопках UI и в промпте** | Partial | T031 — id + options + хэш-id для старых. Но: (а) id чипов S1 сформированы отдельно (`option_ids.py`), не из `Pending.options`; нет задачи их унифицировать; (б) передача PENDING с options в промпт не прописана в T032; (в) лимит исследования — не `case.pending` (`Pending.kind` = 4 значения, `casefile.py:53`), id для него не предусмотрен, хотя T004 считает «limit» видом pending. |

### 4.2 Соответствие старых меток (13 строк)

13s §D1: «Mapping of old labels as in the understanding spec §4» — целиком по ссылке. T005 использует маппинг для
baseline (висячая ссылка, G3).

| # | Старое → новое | Статус | Примечание |
|---|---|---|---|
| 4.M1 | compare, single → Goal(compare/single) | Partial | по ссылке |
| 4.M2 | follow_up_question → Goal(follow_up, question) | Partial | по ссылке |
| 4.M3 | weights_change → Goal(change_priorities) + case_changes | Partial | по ссылке |
| 4.M4 | research_more → Goal(research_more); кнопка → UiAction(research_more) | Partial | кнопочная часть — см. 3.2, задачи нет |
| 4.M5 | critique → reaction=complaint + Goal(critique) | Partial | по ссылке; согласуется с D1-добавлением «complaint never answers pending» |
| 4.M6 | correction → reaction=correction + case_changes | Partial | по ссылке; 013 добавляет `rejections` для «не тот» — совместимо |
| 4.M7 | general_question → Goal(ask_general, question) | Partial | по ссылке |
| 4.M8 | chitchat → goals=[], пустые case_changes, без ответа | Partial | по ссылке; политика goals=[] — T041 косвенно |
| 4.M9 | confirm_yes/no → answer_to_pending.kind=yes/no | Partial | по ссылке |
| 4.M10 | choose_for_me → answer_to_pending.kind=choose_for_me | Partial | по ссылке |
| 4.M11 | rescore → UiAction(panel_edit), source=ui | Partial | задачи нет (см. 3.2) |
| 4.M12 | report_saved → source=system | Missing | ни спека, ни задачи не говорят, как путь `runner._report_saved` (`dialog/runner.py:150`) получает `Intent(source="system")` |
| 4.M13 | поле `relation` удаляется, заменено reaction | Partial | T043/S4 «old labels removed» — `relation` (`interpretation/contracts.py:45`) поимённо не назван |

### 4.3 Проблемные сообщения в новой схеме (5 строк)

| # | Сообщение → ожидание | Статус | Где |
|---|---|---|---|
| 4.P1 | «да, но дизель» → yes + engine: diesel | Covered | T004 (все примеры §B4), T045 |
| 4.P2 | «а что такое DSG?» → ask_general | Covered | T004, g17, T045 |
| 4.P3 | «да, и добавь Hyundai» → yes + compare + add_cars | Covered | T004, T045 |
| 4.P4 | «давай сравним с BMW» → compare + add_cars | Covered | T004, g17, T045 |
| 4.P5 | «все равно хочу дизель» → value **если спрашивали про двигатель** | Partial | пример в T004 есть, но контекстная зависимость (два случая: с вопросом о двигателе / без) не оговорена; ожидаемые Intent для этих 5 сообщений не привязаны к этой таблице |

## 5. Новый поток (§5)

### 5.1 Компоненты

| # | Компонент | Статус | Где / что не так |
|---|---|---|---|
| 5.1.1 | Understander: один вызов, structured output, не смотрит на слова, не меняет дело | Covered | §D1, T032 |
| 5.1.2 | validate_understanding → Understanding или `Rejected(reason)`; старые проверки + pending_id/option_id | Covered | T032 (тип `Rejected` не назван, но «rejected» в записи — T035) |
| 5.1.3 | IntentResolver: единственное место поправок, каждая → overrides; не выбирает действие | Covered | §D1, T032 |
| 5.1.4 | apply_changes: apply(case_changes), ответ на вопрос, факты из текста; не меняет намерение | Covered | T040 |
| 5.1.5 | policy: Intent + ситуация → Action; не читает текст | Covered | §D1 «reads Intent, never text», T041 |

### 5.2 Правила резолвера

| # | Правило | Статус | Где / что не так |
|---|---|---|---|
| 5.2.1 | stale_pending: id не совпал → ответ отброшен, остальное сохранено | Partial | T032 — по имени; семантика (отбросить только ответ) не повторена. Для кнопок см. 4.11 (нет pending_id). |
| 5.2.2 | option_from_ui: pick_option → kind=option, тот же option_id, source=ui | Partial | T032 — по имени |
| 5.2.3 | no_goal_with_pending: нет целей и ответа, есть case_changes по теме → kind=value | Partial | T032 — по имени; «по теме вопроса» не определено |
| 5.2.4 | cars_safety_net: переезжает из apply **без изменений логики** | Covered | T032; «без изменений логики» не сказано, но перенос очевиден |
| 5.2.5 | language_hysteresis: stable_language; при отказе модели язык из чата, не "en" | Covered | T032, T040 |
| 5.2.6 | Удаляются: yes_or_no, choose_for_me, go_ahead, picked_option по тексту, «≤ 3 слова без цифр» | Partial | T042 — списки слов; «≤ 3 слова» убрано в S1 (T012, сделано); `picked_option` поимённо не назван (см. 3.3) |
| 5.2.7 | Аварийный режим: только точное совпадение всей фразы | Covered | §D1, T042 |
| 5.2.8 | …иначе мягкое окончание «сервис перегружен» (§9 риски) | Missing | ни в 13s, ни в 13t. (Есть существующий исход `provider_down`, но связь не прописана.) |

### 5.3 Граф

| # | Требование | Статус | Где / что не так |
|---|---|---|---|
| 5.3.1 | interpret → understand: Understander + проверки + резолвер, пишет `intent` (dict из model_dump) | Covered | T040; 14s §D1/§D2 (секция `understanding`, дамп в JSON для checkpoint) |
| 5.3.2 | apply_delta → apply_changes: без переписывания метки | Covered | T040 |
| 5.3.3 | apply_* не разбирают текст; текст → understand; кнопка → UiAction | Covered | T042 |
| 5.3.4 | После understand с answer_to_pending для подтверждения роутер ведёт в apply_* с готовым ответом | Partial | T042 говорит, что apply_* принимают готовый PendingAnswer, но маршрут understand → apply_* (при ожидании на wait_*) не описан ни в 013, ни в 014 C4 (`Out.next()` для understand: только `apply_changes` / `reply`, 14s §D2). |
| 5.3.5 | Pending снимается только при ответе или явной смене темы (новая цель compare с другими машинами) | Missing | нет ни в спеке, ни в задачах (см. также открытый вопрос 10.5) |
| 5.3.6 | PER_TURN_RESET обнуляет intent; язык из прошлого хода | Covered | T040; 14t T121 (язык в секции `chat`). Внутреннее расхождение: T040 «PER_TURN_RESET resets intent», 14t T121 «PER_TURN_RESET deleted» — в одном релизе (S4 = C3). |

### 5.4 Политика

| # | Требование | Статус | Где / что не так |
|---|---|---|---|
| 5.4.1 | ask_general, follow_up по собранным данным, goals=[] — сразу; при открытом вопросе — ANSWER_AND_REASK | Covered | T041 |
| 5.4.2 | Цели с предусловиями (compare, single, research_more): intake/confirm/research — проверки для цели; **вопрос бота содержит причину** | Partial | «проверки для цели» и текст-причина в вопросе пользователю не закреплены (см. 2.G5) |
| 5.4.3 | Несколько целей: сначала без предусловий, потом первая с предусловиями | Covered | T041 «goals without preconditions answered first» (вторая половина — неявно). Различие по этапам — см. 9.R3. |
| 5.4.4 | Situation получает intent вместо request; Action.reason ссылается на цель и правило | Covered | T041, T043 (Situation не назван поимённо) |

## 6. Промпт (§6)

| # | Требование | Статус | Где / что не так |
|---|---|---|---|
| 6.1 | understander.md заново, ≤ ~800 слов | Covered | §D1, T032 |
| 6.2 | Структура: роль (2–3 предл.), 4 вопроса по блоку на поле, правила фактов коротко и один раз | Missing | структура промпта не упомянута |
| 6.3 | 15–20 примеров из эталона, **на трёх языках, включая все примеры §1** | Partial | T032: «15–20 examples from the set»; три языка и обязательность примеров §1 не сказаны |
| 6.4 | Вход: CASE FILE / PENDING (с options) / **LAST ANSWER** (для reaction) / HISTORY / MESSAGE | Missing | формат входа не описан; LAST ANSWER — новый вход, нигде не упомянут |
| 6.5 | Убрать: ссылки на spec/FR, «пока вопрос открыт — всё ответ», дубли правил персоны | Missing | не перечислено (косвенно следует из «пишется заново») |
| 6.6 | Правила раскладки по CaseDelta (engine_hint, trim_hint) → в description полей схемы | Missing | не упомянуто |

## 7. Наблюдаемость (§7)

| # | Требование | Статус | Где / что не так |
|---|---|---|---|
| 7.1 | turn_id, chat_id | Covered | T033 (таблица), T033 лог ошибок с chat_id/turn_id |
| 7.2 | input: текст или UiAction + открытый вопрос с id | Covered | §D5, T035 |
| 7.3 | model_raw + **версия промпта, имя модели** | Partial | model_raw есть (§D5, T035); версия промпта и имя модели не упомянуты |
| 7.4 | rejected (что и почему) | Covered | §D5, T035 |
| 7.5 | overrides (правило, поле, до, после, причина) | Covered | §D5, T032, T035 |
| 7.6 | intent | Covered | §D5, T035 |
| 7.7 | policy_trail: какие правила проверялись, какое сработало, Action.reason | Partial | поле есть в §D5/T035, но нет задачи, обязывающей политику (T041) выдавать трейл проверенных правил |
| 7.8 | Через порт; ошибка записи не роняет ход, лог с chat_id/turn_id | Covered | §D5, T033 |
| 7.9 | Prometheus: доля ходов с overrides по правилу; доля rejected; доля повторно заданных вопросов | Partial | в 13s §D5 есть; в задачах нет (T006 — eval-gauge, T052 — invariant counter, T062 — сигнал «question repeated» в self-diagnosis, не метрика) |
| 7.10 | previous_signals из intent.reaction этого хода | Covered | T043 |
| 7.11 | Эндпоинт/скрипт «показать понимание хода» по turn_id | Covered | §D5, T035 (CLI) |

## 8. Тестирование и приёмка (§8)

| # | Требование | Статус | Где / что не так |
|---|---|---|---|
| 8.1 | Набор собран **до** нового кода; прогон на старом = точка отсчёта | Covered | S0 (T004, T005), 13s §E |
| 8.2 | 100–150 YAML: дело/фикстура, pending, история, сообщение, ожидаемый Intent (значимые поля), Action.kind | Covered | T004 |
| 8.3 | Источник: все примеры §1 | Covered | T004 |
| 8.4 | Источник: реальные промахи прод (чаты с reaction=complaint/rephrase) | Missing | T004 не упоминает; связан с открытым вопросом 10.2 |
| 8.5 | Источник: «золотые диалоги», упомянутые в промпте | Missing | не упомянуто |
| 8.6 | Покрытие: ru/es/en поровну; каждый вид pending; два намерения; похожие на да/нет | Covered | T004 (плюс наши rejections/stop) |
| 8.7 | Уровень юнит (validate, каждое правило, политика на Intent), каждый коммит | Covered | 13s §E, T032 |
| 8.8 | Уровень eval: настоящая модель; каждое изменение промпта/схемы/правил; ночью | Covered | 13s §E, §G2; T005, T006 |
| 8.9 | Уровень диалогов: 10–15 многоходовых сценариев, фейковые порты, скриптованная модель, каждый коммит | Covered | 13s §E; `backend/tests/golden/` — 17 сценариев (g1–g17), часть `check.sh` |
| 8.A1 | Все примеры §1 проходят | Covered | §E, T045 |
| 8.A2 | answer_to_pending ≥ 97% | Covered | §E, T044 |
| 8.A3 | цели ≥ 92%, Action.kind ≥ 95% | Covered | §E, T044 |
| 8.A4 | Ни одной регрессии против старого кода, где он прав | Covered | §E, T044 |
| 8.A5 | p95 задержки понимания не хуже +20% | Partial | в §E есть; ни одна задача не замеряет задержку старого шага (T005 — только точность) и нового |
| 8.A6 | Каждый ход оставляет turn_understanding | Covered | §E |
| 8.A7 | Пороги — стартовые, уточняются после замера | Covered | §E «thresholds revisited after the baseline» (утверждение владельцем — см. 10.7) |

## 9. Миграция и риски (§9)

### 9.1 Этапы (источник: 6 этапов, 0–5; содержание восстановлено по упоминаниям, G5)

| Этап источника | Что о нём известно из текста | Наш шаг | Статус |
|---|---|---|---|
| 0 | замер старого кода на эталоне (§10 п.7) | S0 (T004–T006) | Covered (T004–T006 ещё не сделаны) |
| 1 | убирает частые промахи §1, независим | S1 (сделан, PR #137) | Covered |
| 2 | формат кнопок/preset («перед этапом 2 проверить потребителей») | S1 T013 (сделан) | Covered, но слит с этапом 1 |
| 3 | политика берёт первую цель; в 11.6 — вместе с шагами 3–4 контракта | S3 (тень) / S4 (переключение) — однозначно не сопоставить | Различие (см. 9.R3, 11.6) |
| 4 | старые ключи читаются до него; алиасы до него; возможный флаг на чат | S4 | Covered (флаг — 10.6) |
| 5 | полная поддержка нескольких целей | S4 (сразу) | Различие (см. 9.R3) |
| — | (нет в источнике) | S2, S5, S6, S7 — идентификация, жалоба/выход, §0a | Добавлено намеренно |

### 9.2 Совместимость checkpoint

| # | Требование | Статус | Где / что не так |
|---|---|---|---|
| 9.C1 | Новые ключи (intent) добавляются; interpretation/request_kind читаются до этапа 4 и удаляются после | Covered | 13s §F (конец); 14s §D6 (исчезают в C3=S4), 14t T122 адаптер. Нет отдельной задачи «удалить старые ключи после S4» — T043 «until removed». |
| 9.C2 | wait_* не переименовываем; interpret и apply_delta — алиасы **до этапа 4** | Различие | Источник: «interpret и apply_delta остаются алиасами до этапа 4». 13t T040 (S4): «Node `understand` (alias `interpret` kept)»; 13s §D2: алиасы «until a release after which no thread waits on them». Мы переименовываем в S4 и держим алиасы дольше. Безопаснее, но иначе. |
| 9.C3 | Pending без id получает id при чтении (стабильный хэш) | Covered | T031, 13s §F |
| 9.C4 | Старые клиенты со словом на кнопке → текст + список вариантов в модель | Covered | T013 (сделано: «Old clients sending text stay served as text»), 13s §F |

### 9.3 Риски

| # | Риск → мера | Статус | Где / что не так |
|---|---|---|---|
| 9.R1 | Дороже/медленнее → дешёвая быстрая модель для understander | Missing | не выбрана и не отслеживается (см. 10.1) |
| 9.R1b | …для кнопок модель не вызывается | Covered | T013 (сделано), `option_from_ui` T032 |
| 9.R2 | Модель недоступна → точное совпадение фразы, иначе «сервис перегружен» | Partial | точное совпадение — T042; мягкое окончание — Missing (5.2.8) |
| 9.R3 | Несколько целей → на этапах 3–4 политика берёт **первую** цель, остальные только в запись; полная поддержка — этап 5 | Contradicted / различие | Источник: «на этапах 3–4 политика берёт первую цель … полная поддержка — этап 5». 13t T041 (S4): «goals without preconditions answered first; ANSWER_AND_REASK …» — полная поддержка сразу при переключении, без промежуточного «первая цель». |
| 9.R4 | Каждая заплатка interpreter.md и списков слов → случай эталона **до удаления** | Missing | T004 не требует инвентаризации заплаток; T042 удаляет списки без этого условия |
| 9.R5 | Код вне архива (delivery.web, клиент) зависит от preset и формата кнопок → проверить всех потребителей перед этапом 2 | Partial | T013 сделан с обратной совместимостью (текст), но аудит потребителей не зафиксирован ни в задаче, ни в отчёте S1 |

## 10. Открытые вопросы (§10)

| # | Вопрос | Статус | Где |
|---|---|---|---|
| 10.1 | Какая модель для understander; бюджет задержки и стоимости на ход | Missing (не решён, не отслеживается) | 13s §G2 решает только стоимость прогона eval (€1–2), не модель роли и не бюджет хода |
| 10.2 | Кто/как собирает реальные промахи прод в набор | Missing | нигде |
| 10.3 | Какие клиенты/эндпоинты шлют preset и кнопки словом | Partial (фактически отвечен S1, не записан) | фронт в репозитории, T013 сделан; ответ нигде не записан как решение |
| 10.4 | ANSWER_AND_REASK всегда или только при коротком ответе | Partial (решён неявно: «всегда») | 13s §D1, T041 — без оговорки длины; в §G не записано |
| 10.5 | Когда считать смену темы и снимать вопрос без ответа | Missing | нигде (см. 5.3.5) |
| 10.6 | Переходный флаг на чат для этапа 4 | Missing (неявно «нет»: тень S3 → жёсткое переключение S4) | не записано как решение |
| 10.7 | Утвердить пороги точности после замера этапа 0 | Partial | 13s §E «revisited after the baseline»; нет шага «владелец утверждает» в T005/T044 |

## 11. Контракт узлов (§11 → спека 014)

Сверка только с резюме §11 (G4).

| # | Пункт | Статус | Где |
|---|---|---|---|
| 11.1 | Проблемы | Covered | 14s §A, §B (B1–B10, с поправкой про `done`) |
| 11.2 | Разделы состояния и владельцы | Covered | 14s §C2, §D1; 14t T101, T120 |
| 11.3 | Узел с явным входом/выходом/следующим шагом, декоратор `@node` | Covered | 14s §C1, §D2, §D4; 14t T101–T104, T130 |
| 11.4 | Карточка один раз за ход | Covered | 14s §C5, §D3; 14t T110–T113 |
| 11.5 | Автоматическая проверка и документирование контракта | Covered | 14s §C6, §E; 14t T105–T107 |
| 11.6a | Шаги 1–2 до переделки понимания | Covered | 14s §D6, §F (C1–C2 «now, beside 013 S1–S2»), §G1 |
| 11.6b | Шаги 3–4 — **вместе с этапом 3** переделки | Различие | Источник: «шаги 3–4 — вместе с этапом 3 переделки». 14s §F/§G1: «C3 with 013 S4; C4 with 013 S5» (владелец: «да, порядок ок»). Шаги 3 и 4 у нас разнесены на два разных шага 013, и ни один не совпадает с S3 (тень). Не оцениваю, что правильно. |

## 12. Что наши спеки добавили сверх источника

| Добавление | Где | Противоречит не-целям источника? |
|---|---|---|
| Идентификация как диалог: подграф, `IdentityState`, инварианты I1–I7, `identification_trail` | 13s §D2, §D5; T050–T055 | Источник: «не трогаем идентификацию» — **снято владельцем** (13s, заголовок). Иначе нет. |
| `rejections: list[Rejection]` в Understanding/Intent; `CaseCar.identity_rejected` | 13s §D1; T020, T021, T030 | Нет: CaseDelta не меняется, поле отдельное; доменная модель машины растёт (не apply()). |
| `GoalKind` + `stop` | 13s §D1; T030, T041 | Нет. |
| Резолвер: `complaint_is_not_an_answer` | 13s §D1; T032 | Нет: резолвер и задуман как место поправок. |
| UiAction `complain` / `quit`, кнопки на каждом вопросе, self-diagnosis issue | 13s §D3; T060–T062 | Нет; касается лимита исследования только в UI. |
| Санитария line-up (≥ 5 моделей, не из одной статьи), purge | 13s §D4, §G3; T014, T015 (сделано) | Нет (часть идентификации). |
| §0a: URL первым, EREV, hints rank not filter | 13s §F S7; T070–T075 | Нет; T071 расширяет `Fuel` — домен, не CaseDelta-правила. |
| 014: retry-чистота `report_node`/`answer_node`, `VersionConflict` | 14s §C4–C5; T112–T113 | Касается узла отчёта, но без смены поведения; источник §11 сам этого требует (по резюме — 11.4). |

## 13. Итог по статусам

| Статус | Кол-во |
|---|---|
| Covered | 77 |
| Partial | 49 |
| Missing | 15 |
| Contradicted / Различие | 3 |

(Счёт по строкам таблиц разделов 1–11; строка 9.R1b считается отдельно; таблица этапов 9.1 и раздел 12 не считаются. «Covered (с оговоркой)» и «Partial (решён неявно…)» — по первому слову.)

## 14. Предлагаемые исправления

| Пункт(ы) | Исправление |
|---|---|
| G1, G2, G3, все «по ссылке» (4.2–4.14, 4.M*, 5.2.1–5.2.3) | Закоммитить `understanding-spec.md`; в T030 написать «точные поля и Literal-значения — understanding-spec.md §4 (дословно), плюс `stop`, `rejections`, `complain`/`quit`»; в T032 — «семантика правил — §5.2»; в T005 исправить ссылку на таблицу; обновить примечание S0. |
| 3.1, 3.2, 4.M4, 4.M11 | Новая задача в S4 (T046): `car_edit` → `UiAction(edit_car)` с точными ошибками; preset `research_more`/`rescore` → `UiAction(research_more/panel_edit)`, `source="ui"`. |
| 3.3, 5.2.6 | В T042 назвать удаление стадии `interpretation/stages/picked_option.py` и её вызовов. |
| 3.6, 5.3.5, 10.5 | В T040: «не отвечено → pending остаётся; снимается только ответом или сменой темы (новая цель compare с другими машинами)»; критерий смены темы — вынести решением владельца в §G. |
| 3.7 | В T042 упомянуть удаление дубля `_card_edit` (`nodes/confirm.py`) в пользу `UiAction(edit_car)`. |
| 4.10, 4.11, 4.15 | В T031: чипы строятся из `Pending.options[].id` (замена id-схемы `option_ids.py`), кнопка шлёт `pending_id`; решить, получает ли лимит исследования pending-id. |
| 4.13, 4.M12 | В T040/T043: путь `report_saved` строит `Intent(source="system")`; поле `source` в записи. |
| 4.M13 | В T043 явно: удалить `Interpretation.relation`. |
| 4.P5 | В T004: «все равно хочу дизель» — два случая (вопрос о двигателе открыт / нет); ожидания пяти сообщений — по таблице §4. |
| 2.G5, 5.4.2 | В T041: вопрос пользователю содержит причину («Чтобы сравнить, нужен год Prado»); правила intake/confirm/research — проверки предусловий цели. |
| 5.2.8, 9.R2 | В T042: модель недоступна и нет точного совпадения → мягкое окончание «сервис перегружен» (связать с `provider_down`). |
| 5.3.4 | В T040 (и 14t T130): маршрут understand → `apply_*` подтверждения, когда `answer_to_pending` отвечает на ожидающий wait_*; добавить ветку в `UnderstandOut.next()`. |
| 5.3.6 | Согласовать T040 и 14t T121: в S4/C3 `PER_TURN_RESET` удаляется, сброс `intent` делает `begin_turn`. |
| 6.2–6.6 | В T032 закрепить структуру промпта (§6: роль, 4 блока, правила фактов), формат входа с PENDING и LAST ANSWER, 3 языка + все примеры §1 в 15–20 примерах, что удаляется, перенос правил CaseDelta в description полей. |
| 7.3, 7.7 | В T033/T035: в `model_raw` версия промпта и имя модели; в T041: политика отдаёт `policy_trail` (проверенные правила, сработавшее, reason). |
| 7.9 | Новая задача в S3/S4: метрики `understanding_overrides_total{rule}`, доля rejected, доля повторно заданных вопросов. |
| 8.4, 8.5, 10.2 | В T004: источники — промахи прод (чаты с complaint/rephrase из `turn_understanding`/tracing) и «золотые диалоги» из interpreter.md; ответ на 10.2 — в §G. |
| 9.R4 | В T004/T042: инвентаризация заплаток interpreter.md и списков слов → случай набора до удаления (чек-лист в PR). |
| 8.A5 | В T005: замер p95 шага понимания на старом коде; в T044 — сравнение. |
| 9.R1, 10.1 | Решение владельца в 13s §G: модель роли understander и бюджет задержки/стоимости на ход. |
| 9.R5, 10.3 | Записать в 13s §G/отчёт S1 итог аудита потребителей preset/кнопок (фронт в репо; старые клиенты — как текст). |
| 10.4, 10.6, 10.7 | Записать в 13s §G: ANSWER_AND_REASK «всегда»; флага на чат нет (тень S3 → переключение S4) или есть; пороги утверждает владелец после T005. |
| 9.R3 | Различие: решить и записать — полная поддержка нескольких целей сразу в S4 (как у нас) или «первая цель» в S4 и полная позже (как в источнике). |
| 9.C2 | Различие: отметить в 13s §F, что алиасы interpret/apply_delta живут дольше этапа 4 (до релиза без ожидающих потоков). |
| 11.6b | Различие: отметить в 14s §D6, что источник ставил C3–C4 вместе с этапом 3; владелец утвердил C3↔S4, C4↔S5. |
| G4 | Сохранить оригинальный текст §11 дословно. |
