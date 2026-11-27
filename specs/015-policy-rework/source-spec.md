# Source: owner's policy spec (verbatim, received 2026-11-27)

Saved as given; the working spec is `spec.md` beside this file, the coverage check is `coverage-audit.md`.

---

Спека: переделка политики действий (policy) — дизайн, надёжность, трассируемость
Nov 26, 2026 · @Miguel

## 1. Контекст и проблемы

Политика решает, что бот делает дальше, но сейчас нельзя ни быстро понять, на чём основано решение, ни восстановить его после хода. Переделка касается dialog/nodes/understand.policy_node, route_policy, dialog/policy/* и списка POLICY_ROUTES в graph.py.

Как работает сейчас. Узел собирает 14 аргументов из шести источников и вызывает decide(). Та упаковывает их в Situation и прогоняет по 10 правилам RULES; первое не-None побеждает, иначе answer_or_report. Узел пишет decision, action, hops; route_policy по словарю выбирает следующий узел. За ход это повторяется до 8 раз (цикл assess → policy → … → assess).

| # | Проблема | Где в коде | Чем опасно |
|---|---|---|---|
| P1 | Факты из шести источников: доска, БД (карточка + fingerprint), settings(), ref.search, модуль чужого узла | policy_node | решение нельзя понять и воспроизвести без чтения шести мест; до 16 запросов в БД за ход |
| P2 | Молчаливые умолчания | request_kind or "compare", get("case_changed", True), get("assessments", {}) + CarState() для машины без оценки | ошибка выше по графу становится «странным поведением»: лишнее исследование, лишний отчёт |
| P3 | Склеенный флаг | research_declined or research_done | правила не отличают «отказался» от «уже сделано» |
| P4 | Логика решения вне политики | nodes/feasibility.pending (хэш условий в модуле узла); пороги в settings() мимо Ports | политику нельзя протестировать без подмены глобальных настроек |
| P5 | Одно решение в трёх видах | Action → decision (dict) → action (строка); action пишут и другие узлы | action="ASK" значит и «политика спросила», и «модель не поняла» |
| P6 | Маршруты в трёх местах | словарь в route_policy, POLICY_ROUTES, ActionKind | новое действие без маршрута = KeyError посреди хода |
| P7 | Лишние слои | decide() с 14 аргументами → Situation с теми же полями; RulesInOrder() на каждый вызов; неиспользуемый протокол Policy | каждое новое поле правится в трёх местах |
| P8 | Нет следа решения | сохраняется только Action.reason | «почему бот спросил, а не ответил?» — только чтением кода |
| P9 | Правила видят одну метку request | Situation.request: RequestKind | намерение человека учитывается только в начале и в конце цепочки |

Связь с другой спекой: P9 решается входом Intent из «Спеки: переделка слоя понимания намерений». Эта спека описывает политику так, чтобы она работала и со старым request, и с новым Intent.

## 2. Цели, не-цели и критерии качества

Политика становится чистой функцией от одного типизированного входа, и каждое её решение оставляет запись, по которой его можно объяснить и повторить.

Цели
1. Детерминированность. decide(situation, config) -> Decision — чистая функция без I/O, глобальных переменных и часов. Одинаковый вход — одинаковое решение.
2. Один вход. Всё, от чего зависит решение, лежит в Situation и PolicyConfig. Ничего из БД, settings() или чужих модулей внутри правил.
3. Никаких молчаливых умолчаний. Отсутствующий вход — ошибка контракта с именем поля, а не подставленное значение.
4. Честные факты. Каждый флаг означает ровно одно; склейки вроде declined or done делаются в правиле, явно и с именем.
5. Одна таблица маршрутов. ActionKind → узел задано один раз; из неё строятся роутер и рёбра графа.
6. Полный след. Каждый проход пишет DecisionTrace: вход, все проверенные правила с исходом и причиной, итог.
7. Читаемость. Правило читается само по себе: имя, условие срабатывания, действие, причина на русском или английском без ссылок на spec NNN.

Не-цели
- Не меняем поведение политики на первом этапе: сначала тот же порядок правил с новым каркасом, потом — переход на «политику от цели» из спеки понимания.
- Не отдаём выбор действия модели.
- Не трогаем узлы, куда ведут действия (отчёт, исследование, подтверждения), кроме их регистрации в таблице маршрутов.

Измеримые критерии

| Критерий | Сейчас | Цель |
|---|---|---|
| Источников данных у решения | 6 | 2 (Situation, PolicyConfig) |
| Запросов в БД от политики за ход | до 16 | 0 (данные из кеша хода) |
| .get(...) с умолчанием при сборке входа | 8 | 0 |
| Мест, где задан маршрут действия | 3 | 1 |
| Ходов с полным следом решения | 0% | 100% |
| Покрытие правил табличными тестами | неизвестно (тестов нет в архиве) | 100% веток, каждое правило: «сработало» и «не сработало» |
| mypy --strict на dialog/policy | нет (Any, cast) | чисто, без cast и Any |

## 3. Новая архитектура

Узел только собирает вход и пишет след; решение принимает чистая функция decide, а куда идти дальше — одна таблица ROUTES.

| Слой | Модуль | Зависит от | Не зависит от |
|---|---|---|---|
| Контракты | dialog/policy/contracts.py | domain | всего остального |
| Правила | dialog/policy/rules/*.py | контракты, domain | nodes, infrastructure, settings, LangGraph |
| Решение | dialog/policy/decide.py (RULES, decide) | правила | то же |
| Сборка входа | dialog/policy/situation.py (situation_from) | контракты, разделы доски | БД, LangGraph |
| Маршруты | dialog/policy/routes.py (ROUTES) | ActionKind, id узлов | кода узлов |
| Узел | dialog/nodes/policy.py | всё выше + TurnContext | — |
| След | порт DecisionLog + репозиторий в infrastructure | контракты | правил |

Правила и decide импортируются и тестируются без БД, LangGraph и модели. policy_node уходит из nodes/understand.py в свой модуль.

## 4. Модель данных

Шесть типов, все неизменяемые (frozen), все в dialog/policy/contracts.py. Ни одно поле не имеет умолчания, которое может спрятать ошибку.

```python
class CarFacts(BaseModel):
    """Что известно об одной машине к моменту решения (бывший CarState)."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    key: str
    identity_known: bool
    in_catalog: bool
    ambiguous: bool
    plausible_generations: int
    data_fresh: bool

class ResearchStatus(StrEnum):
    NOT_NEEDED = "not_needed"     # все данные свежие
    PENDING = "pending"           # нужно, ещё не спрашивали / не запускали
    APPROVED = "approved"         # человек согласился на стоимость
    DECLINED = "declined"         # человек отказался
    DONE = "done"                 # в этом ходе уже исследовали

class Situation(BaseModel):
    """Всё, от чего зависит решение одного прохода. Собирается один раз, в одном месте."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    case: CaseFile
    request: RequestKind                    # после спеки понимания: intent: Intent
    cars: Mapping[str, CarFacts]            # ровно по одной записи на каждую машину дела
    cost_estimate_eur: Decimal
    research: ResearchStatus                # вместо cost_approved + research_declined + research_done
    case_changed: bool
    feasibility_pending: bool
    last_report_fingerprint: str | None     # None = отчёта в чате ещё не было (факт, не умолчание)
    pass_no: int                            # номер прохода в ходе, с 1

    @model_validator(mode="after")
    def _cars_match_case(self) -> Self:
        keys = {c.key for c in self.case.cars}
        if set(self.cars) != keys:
            raise PolicyInputError(f"cars facts {sorted(self.cars)} != case cars {sorted(keys)}")
        return self

class PolicyConfig(BaseModel):
    """Настройки политики. Собираются при старте, проверяются сразу, лежат в Ports."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    confirm_threshold_eur: Decimal = Field(gt=0)
    hard_cap_eur: Decimal = Field(gt=0)
    max_passes: int = Field(ge=2, le=20)
    intake: IntakeLimits

    @model_validator(mode="after")
    def _cap_above_threshold(self) -> Self:
        if self.hard_cap_eur < self.confirm_threshold_eur:
            raise ValueError("hard_cap_eur < confirm_threshold_eur")
        return self

class RuleOutcome(BaseModel):
    """Исход одного правила: сработало с действием или пропущено с причиной."""
    model_config = ConfigDict(frozen=True)
    rule: str                     # имя правила, стабильное (идёт в метрики)
    action: Action | None         # None = пропустило
    why: str                      # причина в обоих случаях: «есть машина без версии: car#2» / «все версии известны»

class Decision(BaseModel):
    """Результат прохода: действие + полный след того, как к нему пришли."""
    model_config = ConfigDict(frozen=True)
    action: Action
    decided_by: str               # имя сработавшего правила
    trail: tuple[RuleOutcome, ...] # все проверенные правила до сработавшего включительно
    pass_no: int
```

Что изменилось по сравнению с текущим кодом

| Было | Стало | Почему |
|---|---|---|
| cost_approved, research_declined, research_done, склеенные через or | research: ResearchStatus | одно состояние вместо трёх флагов, невозможные комбинации невыразимы |
| cars.get(key, CarState()) | cars обязан содержать каждую машину (валидатор) | машина без оценки = ошибка, а не «известная без данных» |
| cost_estimate_eur: float \| None | Decimal, обязательно | деньги не во float; нет оценки — assess обязан поставить 0 явно |
| hops + max_hops в аргументах | pass_no в Situation, max_passes в PolicyConfig | факт отделен от настройки |
| пороги из settings(), лимиты из ref.search | PolicyConfig в Ports | один объект, проверяется при старте, легко подменить в тесте |
| Action.reason | Decision.trail + decided_by + RuleOutcome.why | видны и пропущенные правила |
| decide() с 14 аргументами | decide(situation, config) | новое поле добавляется в одно место |

## 5. Правила

Правило — класс с именем и одним методом check, который всегда возвращает RuleOutcome: и когда сработало, и когда нет, с причиной.

### 5.1. Интерфейс

```python
class Rule(Protocol):
    name: ClassVar[str]            # стабильное имя: "intake.identity", "research.stale_data"
    stage: ClassVar[Stage]         # LIMITS | GENERAL | INTAKE | CONFIRM | RESEARCH | ANSWER

    def check(self, s: Situation, cfg: PolicyConfig) -> RuleOutcome: ...

# помощники, чтобы правило читалось как текст
def fire(rule: type[Rule], action: Action, why: str) -> RuleOutcome: ...
def skip(rule: type[Rule], why: str) -> RuleOutcome: ...
```

Порядок задан одним кортежем и сгруппирован по стадиям. Последнее правило — такое же правило, которое срабатывает всегда, а не скрытый return answer_or_report(s) после цикла.

```python
RULES: Final[tuple[Rule, ...]] = (
    # LIMITS — защита от циклов и служебные ходы
    PassLimit(), ReportAfterTimeout(), PanelEdit(),
    # GENERAL — нет машин или вопрос не про них
    ProposeCandidates(), GeneralAnswer(),
    # INTAKE — чего не хватает, чтобы сравнивать
    IdentityStep(), MissingEssentials(),
    # CONFIRM — что человек должен подтвердить
    IntakeCard(), ConfirmVariants(),
    # RESEARCH — данных не хватает
    StaleData(),
    # ANSWER — всё готово; последнее, срабатывает всегда
    AnswerOrReport(),
)

def decide(s: Situation, cfg: PolicyConfig) -> Decision:
    trail: list[RuleOutcome] = []
    for rule in RULES:
        outcome = rule.check(s, cfg)
        trail.append(outcome)
        if outcome.action is not None:
            return Decision(action=outcome.action, decided_by=rule.name,
                            trail=tuple(trail), pass_no=s.pass_no)
    raise PolicyBug("AnswerOrReport must always fire")   # недостижимо, проверяется тестом
```

### 5.2. Пример: StaleData до и после

Сейчас:

```python
def stale_data(s: Situation) -> Action | None:
    stale = [c.key for c in s.case.cars if not s.state[c.key].data_fresh]
    if not stale or s.research_declined:          # declined здесь значит ещё и «done»
        return None
    est = s.cost_estimate_eur or 0.0
    if est >= s.confirm_threshold_eur and not s.cost_approved:
        return Action(kind="CONFIRM_COST", ...)
    return Action(kind="RESEARCH", ...)
```

После:

```python
class StaleData:
    """Данных по текущим критериям не хватает: спросить про стоимость или исследовать."""
    name = "research.stale_data"
    stage = Stage.RESEARCH

    def check(self, s: Situation, cfg: PolicyConfig) -> RuleOutcome:
        stale = [k for k, car in s.cars.items() if not car.data_fresh]
        if not stale:
            return skip(self, "данные свежие по всем машинам")
        match s.research:
            case ResearchStatus.DONE:
                return skip(self, f"уже исследовали в этом ходе, не хватает: {stale}")
            case ResearchStatus.DECLINED:
                return skip(self, "человек отказался от исследования")
            case ResearchStatus.APPROVED:
                return fire(self, Action.research(stale), "стоимость одобрена")
            case ResearchStatus.PENDING | ResearchStatus.NOT_NEEDED:
                if s.cost_estimate_eur >= cfg.confirm_threshold_eur:
                    over = s.cost_estimate_eur > cfg.hard_cap_eur
                    return fire(self, Action.confirm_cost(stale, over_cap=over),
                                f"оценка €{s.cost_estimate_eur} ≥ порога €{cfg.confirm_threshold_eur}")
                return fire(self, Action.research(stale),
                            f"оценка €{s.cost_estimate_eur} ниже порога")
```

Что стало лучше: все ветки перечислены (match по enum, mypy проверяет полноту через assert_never); «отказался» и «уже сделано» различаются; у каждого исхода есть человеческая причина; фабрики Action.research(...) вместо ручной сборки Action(kind="RESEARCH", ...).

### 5.3. Правила написания правил

- Правило читает только Situation и PolicyConfig. Импорт из dialog.nodes, infrastructure или settings запрещён (проверка import-linter).
- Одно правило — один вопрос о ситуации. Если в правиле больше трёх веток с разными действиями, оно делится (кандидат: сегодняшнее answer_or_report с шестью исходами).
- why пишется для человека, который разбирает жалобу: конкретные ключи машин, суммы, имена полей.
- Имена правил стабильны — они идут в метрики и записи ходов. Переименование = миграция дашбордов.
- Ссылки на требования (spec NNN, FR-NNN) — в одном поле requirement: ClassVar[str | None], а не в комментариях по всему телу.

## 6. Узел policy и маршрутизация

Узел становится тонким: собрать Situation, вызвать decide, записать след. Вся сборка входа — в одной функции, которую можно тестировать отдельно.

### 6.1. Узел

```python
class PolicyIn(BaseModel):
    """Разделы доски, нужные политике. Нет раздела → ContractError до вызова узла."""
    model_config = ConfigDict(frozen=True)
    understanding: Understood            # request / intent
    applied: Applied                     # case_changed
    assessment: Assessment               # cars facts, cost_estimate, feasibility
    confirm: ConfirmState                # cost approved / declined
    research: ResearchState              # done in this turn
    decision: DecisionHistory            # прошлые проходы этого хода (пусто на первом)

class PolicyOut(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    decision: DecisionHistory            # прежние проходы + этот

    def next(self) -> NodeId:
        return ROUTES[self.decision.last.action.kind]

@node("policy", reads=PolicyIn, writes=PolicyOut, retry=Retry.NONE)
async def policy(inp: PolicyIn, ctx: TurnContext) -> PolicyOut:
    situation = situation_from(inp, case=await ctx.case(),
                               last_fingerprint=await ctx.last_report_fingerprint())
    decision = decide(situation, ctx.ports.policy_config)
    ctx.trace.decision(situation, decision)          # раздел 7
    return PolicyOut(decision=inp.decision.append(decision))

def situation_from(inp: PolicyIn, *, case: CaseFile, last_fingerprint: str | None) -> Situation:
    """Единственное место, где доска превращается в факты политики. Чистая функция."""
    return Situation(
        case=case,
        request=inp.understanding.request,
        cars=inp.assessment.cars,
        cost_estimate_eur=inp.assessment.cost_estimate_eur,
        research=research_status(inp.confirm, inp.research, inp.assessment),
        case_changed=inp.applied.case_changed,
        feasibility_pending=inp.assessment.feasibility.pending_for(case),   # логика из nodes/feasibility → в домен
        last_report_fingerprint=last_fingerprint,
        pass_no=len(inp.decision.passes) + 1,
    )
```

- ctx.case() и ctx.last_report_fingerprint() читают из БД один раз за ход и держат результат в памяти. Сохранение карточки другим узлом обновляет кеш.
- hops исчезает как отдельный счётчик: номер прохода = длина истории решений. Рассинхронизация невозможна.
- Ключ action на доске исчезает. Итог хода для строки turns и метрик берётся из decision.last или из reply.outcome терминального узла — и никогда из узла понимания.

### 6.2. Одна таблица маршрутов

```python
ROUTES: Final[Mapping[ActionKind, NodeId]] = MappingProxyType({
    "ANSWER_GENERAL":    "general",
    "ASK":               "ask",
    "SELECT_CANDIDATES": "select_candidates",
    "CONFIRM_INTAKE":    "prepare_intake",
    "CONFIRM_VARIANTS":  "prepare_variants",
    "CONFIRM_COST":      "prepare_cost",
    "FEASIBILITY":       "prepare_feasibility",
    "RESEARCH":          "plan_research",
    "ANSWER_FROM_CONTEXT": "answer",
    "REPORT":            "report",
    "RESCORE":           "report",     # отчёт пересчитывает и говорит, что изменилось
})
```

- Из ROUTES строятся и рёбра графа (g.add_conditional_edges("policy", ..., set(ROUTES.values()))), и сам переход. Список POLICY_ROUTES и словарь в route_policy удаляются.
- Тест полноты: set(ROUTES) == set(get_args(ActionKind)), и каждое значение — существующий узел графа. Новое действие без маршрута не проходит CI, а не падает KeyError в продакшене.
- Каждое действие также помечено: терминальное (заканчивает ход) или возвращает в assess. Это нужно для теста завершения (раздел 9).

## 7. Трассируемость

По любому ходу можно за одну команду получить ответ на вопрос «почему бот сделал X» и переиграть решение локально.

### 7.1. Запись решения

Каждый проход политики пишет одну строку в таблицу policy_decisions через порт DecisionLog:

| Поле | Содержимое |
|---|---|
| chat_id, turn_id, pass_no | адрес решения |
| situation | Situation.model_dump() без карточки + case_version (карточка уже версионирована в case_files) |
| config_hash | хэш PolicyConfig, сам конфиг — в отдельной таблице по хэшу |
| rules_version | версия набора правил (хэш имён и порядка RULES + версия пакета) |
| trail | [{rule, fired, why}] — все проверенные правила |
| decided_by, action | сработавшее правило и действие целиком |
| next_node | куда пошёл граф |

Полнота записи проверяется свойством: из situation + case_files[case_version] + конфига по config_hash функция decide даёт то же action (тест в разделе 9).

### 7.2. Логи и метрики

- Структурный лог policy.decided с полями chat_id, turn_id, pass_no, decided_by, action.kind, next_node — одна строка на проход.
- Спан OpenTelemetry policy.decide внутри спана хода, с теми же атрибутами (если в observability есть трейсинг; иначе только лог).
- Prometheus: policy_decisions_total{rule, action}, policy_passes_per_turn (гистограмма), policy_pass_limit_total (сколько ходов упёрлось в лимит проходов), policy_input_errors_total{field}.
- Алерт: policy_pass_limit_total растёт — в графе цикл, который правила не разорвали.

### 7.3. Команда «почему»

```
$ python -m automind.chat.dialog.policy why <turn_id>
проход 1  case v12  → ASK (intake.identity)
  ✓ limits.pass_limit         проход 1 из 8
  ✓ limits.panel_edit         запрос не от панели
  ✓ general.candidates        в деле 2 машины
  ✓ general.answer            запрос compare
  ● intake.identity            car#2: неизвестен год (б/у, 3 поколения подходят)
→ next: ask
```

Команда читает policy_decisions; те же данные отдаёт служебному эндпоинту для админки. Флаг --replay пересчитывает решение на текущем коде и показывает, изменилось ли оно.

### 7.4. Воспроизведение из продакшена

- Любая запись policy_decisions выгружается в YAML-фикстуру (команда export <turn_id>) и сразу становится тестом из раздела 9.
- Персональные данные из карточки при выгрузке маскируются (слова пользователя в evidence, регион).

## 8. Надёжность

Политика либо принимает решение на полных и согласованных данных, либо громко падает с именем проблемы. Тихого «что-то подставили и пошли дальше» не бывает.

### 8.1. Инварианты входа

| Инвариант | Где проверяется | Нарушение |
|---|---|---|
| У каждой машины дела есть CarFacts, и нет лишних | валидатор Situation | PolicyInputError |
| Оценка и карточка относятся к одной версии: assessment.case_version == case.version | situation_from | PolicyInputError("assessment is stale") |
| cost_estimate_eur ≥ 0 | тип Decimal + Field(ge=0) | ошибка валидации |
| pass_no ≤ max_passes + 1 | PassLimit срабатывает на max_passes; проход сверх него — баг | PolicyBug |
| Нет карточки, но есть оценки машин | валидатор Situation | PolicyInputError |

Инвариант про версию ловит типичную ошибку цикла: узел подтверждения сохранил карточку, а политика вызвана на старой оценке без assess. По графу такого быть не должно, и инвариант это гарантирует.

### 8.2. Как обрабатываются ошибки

- PolicyInputError и PolicyBug — ошибки программы, не пользователя. Ход завершается через существующий механизм мягких окончаний новым типом run_internal_error («что-то пошло не так, попробуйте ещё раз») и статусом FAILED.
- В лог и метрику policy_input_errors_total{field} попадает имя поля и turn_id. Ретраев нет: повтор на тех же данных даст ту же ошибку.
- Исключение внутри правила не перехватывается и не превращается в «пропустить правило»: молча пропущенное правило = другое решение без следа.

### 8.3. Конфиг

- PolicyConfig собирается в точке сборки приложения из settings и search.yaml один раз. Невалидный конфиг — сервис не стартует.
- В коде политики нет ни settings(), ни ref.search, ни констант DEFAULT_* как умолчаний аргументов. Умолчания живут в одном месте — в сборке конфига.
- Хэш конфига пишется в каждое решение (раздел 7): изменение порога видно в истории.

### 8.4. Данные хода

- Карточка и fingerprint читаются из кеша хода, а не из БД на каждом проходе. Меньше запросов — меньше мест для StoreUnavailable посреди хода.
- Политика ничего не пишет в БД, кроме записи решения. Запись решения идемпотентна по ключу (turn_id, pass_no): повтор узла после рестарта не создаст дубль.
- Ошибка записи решения не роняет ход, но логируется с уровнем ERROR и считается метрикой. Никаких except Exception: return.

## 9. Тестирование

Политика — чистая функция, поэтому все тесты идут без БД, модели и LangGraph и занимают секунды.

| Вид | Что проверяет | Как |
|---|---|---|
| Табличные тесты правил | каждая ветка каждого правила: «сработало с таким действием» и «пропустило с такой причиной» | pytest.mark.parametrize по строкам: имя случая, билдер Situation, ожидаемый RuleOutcome |
| Порядок правил | приоритеты не ломаются при перестановке | ситуации, где срабатывают два правила; ожидается более раннее |
| Свойства (Hypothesis) | decide никогда не бросает PolicyBug; trail непустой и заканчивается сработавшим правилом; при pass_no = max_passes решение терминальное | генератор случайных валидных Situation |
| Завершение цикла | цикл assess → policy → … заканчивается до лимита и без него | симулятор: каждое нетерминальное действие применяет свой эффект к Situation (подтверждение → APPROVED, исследование → DONE + свежие данные); проверяем, что за ≤ 4 прохода приходим к терминальному |
| Эталонные ситуации | реальные решения из продакшена не меняются случайно | YAML-фикстуры из export <turn_id> (раздел 7.4); изменение решения требует явно обновить фикстуру |
| Воспроизводимость записи | из записи policy_decisions решение пересчитывается в то же | round-trip: decide → запись → чтение → decide |
| Контракт маршрутов | у каждого ActionKind есть маршрут и узел существует | set(ROUTES) == set(get_args(ActionKind)) + проверка узлов собранного графа |
| Границы модулей | правила не импортируют nodes, infrastructure, settings | import-linter в CI |
| Сборка входа | situation_from падает на каждом нарушении инварианта из 8.1 | по одному тесту на инвариант |

Билдер ситуаций — один на все тесты, чтобы случаи читались как текст:

```python
s = (situation()
     .with_car("car#1", identified=True, fresh=False)
     .with_car("car#2", identified=False, generations=3)
     .request("compare")
     .cost("0.45")
     .research(ResearchStatus.PENDING)
     .build())
assert decide(s, CFG).decided_by == "intake.identity"
```

Регрессия против старого кода. На шаге 1 миграции обе реализации прогоняются на одних и тех же случайных ситуациях (Hypothesis, 10 000 примеров); action.kind должен совпадать везде, кроме задокументированных отличий (например, ситуации с машиной без оценки, где новый код падает по замыслу).

## 10. План миграции и риски

Пять шагов; после каждого система работает, и каждый можно выкатить отдельно. Поведение политики до шага 5 не меняется.

1. Каркас без изменения поведения. Rule с RuleOutcome, decide(situation, config) -> Decision со следом, AnswerOrReport как последнее правило. Правила переносятся 1:1. Приёмка: регрессия против старого кода без отличий на 10 000 случайных ситуаций.
2. Один вход и конфиг. situation_from, PolicyConfig в Ports, кеш карточки и fingerprint в TurnContext, перенос feasibility.pending в домен. Инварианты 8.1 в продакшене сначала только пишут метрику, через неделю без срабатываний — становятся ошибками.
3. Трассировка. Таблица policy_decisions (миграция Alembic), порт DecisionLog, логи и метрики, команды why и export.
4. Маршруты и доска. ROUTES вместо route_policy + POLICY_ROUTES; decision как история проходов вместо decision + action + hops. Старые ключи читаются переходным адаптером, пока в checkpoint есть ходы в статусе WAITING.
5. Честные факты. ResearchStatus вместо трёх флагов; правила начинают различать DONE и DECLINED. Это первое осознанное изменение поведения, с обновлением эталонных ситуаций. Дальше — переход на Intent по спеке понимания.

Риски

| Риск | Что делаем |
|---|---|
| Инварианты начнут ронять ходы, которые сейчас «как-то работают» | шаг 2: сначала только метрика; каждое срабатывание — баг выше по графу, чиним там |
| Таблица policy_decisions растёт (до 8 строк на ход) | без карточки в строке (только case_version); партиции по месяцу, хранение 90 дней |
| Ходы в WAITING на момент выката со старыми ключами доски | переходный адаптер читает hops, cost_approved, research_*; удаляется, когда таких ходов 0 |
| Decimal вместо float трогает assess и фикстуры | конверсия на границе situation_from (округление до цента), внутри assess — позже |
| Код вне архива читает action или decision с доски | перед шагом 4 — grep по delivery.web, observability и дашбордам |

## 11. Открытые вопросы

- [ ] Есть ли в observability трейсинг OpenTelemetry, или след пишем только в лог и таблицу? (код вне архива)
- [ ] Сколько хранить policy_decisions: 90 дней достаточно для разбора жалоб?
- [ ] Разделить ли AnswerOrReport (шесть исходов) на отдельные правила уже на шаге 1 или после перехода на Intent?
- [ ] Нужна ли админке страница «почему» или достаточно CLI?
- [ ] Какой max_passes на самом деле нужен: сейчас 8, тест завершения ожидает ≤ 4. Уточнить по метрике policy_passes_per_turn после шага 3.
