"""What the golden message set must cover (spec 013 T004) and the cross-checks of cases against fixtures.

The frozen lists below are the sources understanding-spec §9 says must become cases before they leave the main path:
every §1 example, every rule / example of `interpreter.md` v5, every word of `phrases._YES/_NO/_CHOOSE/_GO`. The unit
test fails when a source changes (prompt version, word list) so the set is revisited first.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from tests.eval.understanding.fixture_models import Fixtures
from tests.eval.understanding.schema import Case
from tests.eval.understanding.vocab import Category, PendingKind, Source

CASES_MIN, CASES_MAX = 100, 150
LANG_MIN_SHARE = 0.28  # "ru / es / en roughly even": each language at least this share of the set

# understanding-spec §1 "Примеры промахов" = spec 013 §B4 (the messages as written there)
SPEC1_MESSAGES: tuple[str, ...] = (
    "да, но дизель", "давно хотел дизель", "дайте подумать", "para mi familia", "answer me about fuel",
    "все равно хочу дизель", "do you have any...", "давай сравним с BMW", "а что такое DSG?", "да, и добавь Hyundai",
    "переформулируйте",
)  # fmt: skip
# understanding-spec §4 "Как выглядят проблемные сообщения в новой схеме"
PROBLEM_TABLE: tuple[str, ...] = (
    "да, но дизель", "а что такое DSG?", "да, и добавь Hyundai", "давай сравним с BMW", "все равно хочу дизель",
)  # fmt: skip
DIESEL = "все равно хочу дизель"

# chat/dialog/phrases.py as of interpreter v5 / spec 013 S2 (the test compares them with the module)
WORD_LISTS: dict[str, tuple[str, ...]] = {
    "YES": ("continue", "go on", "go ahead", "keep going", "yes", "ok", "okay", "sure", "proceed", "run",
            "да", "давай", "продолж", "дальше", "ок", "поехали", "запуск", "sí", "si", "sigue", "continúa", "continua",
            "adelante", "vale"),
    "NO": ("stop", "no", "enough", "answer", "nein", "нет", "стоп", "хватит", "достаточно", "отвечай", "ответь",
           "basta", "para", "responde"),
    "CHOOSE": ("choose for me", "you choose", "any", "whatever", "doesn't matter", "dont care", "don't care",
               "любой", "любая", "любую", "любое", "выбери сам", "выбери ты", "на твой выбор", "на ваш выбор",
               "всё равно", "все равно", "неважно", "не важно", "cualquiera", "elige tú", "elige tu", "me da igual",
               "da igual"),
    "GO": ("вперед", "вперёд", "давай", "продолжай", "дальше", "к сравнению", "сравнивай", "go ahead", "go on",
           "continue", "proceed", "adelante", "sigue", "continúa", "continua", "compara"),
}  # fmt: skip

INTERPRETER_VERSION = "interpreter v5"
# every rule of chat/dialog/prompts/interpreter.md v5 (in prompt order) and its numbered examples
INTERPRETER: tuple[str, ...] = (
    "correction_replace", "rejections", "set_car_context", "copy_hints", "model_line", "real_manufacturer",
    "condition", "choose_from_make", "replaced_car", "persona", "profile_basis", "ownership_years", "age_usage",
    "priorities", "unmapped_wishes", "budget", "budget_intent_answer", "running_cost_limit", "needs",
    "numbers_evidence", "race", "smart_buyer", "pending_confirm", "pending_choose", "pending_nonsense",
    "profile_family", "annual_km", "gearbox_drive", "trim_version", "pending_cars_existing_keys", "brand_explained",
    "engine_hint", "engine_correction", "url", "region", "distance_range", "new_used_all", "follow_up",
    "research_more", "critique", "general_question", "language", "relation_continues", "relation_rephrase",
    "relation_correction", "relation_complaint", "relation_thanks", "relation_new_topic",
    "ex1", "ex2", "ex3", "ex4", "ex5", "ex6", "ex7", "ex8", "ex9", "ex10", "ex10b", "ex11", "ex12", "ex13", "ex14",
    "ex15", "ex16", "ex17",
)  # fmt: skip

# T004's coverage lines with the least number of cases each
REQUIRED: dict[Category, int] = {
    Category.SPEC1: len(SPEC1_MESSAGES), Category.PROBLEM_TABLE: len(PROBLEM_TABLE), Category.REJECTION: 6,
    Category.STOP: 4, Category.COMPLAINT: 6, Category.LOOKALIKE_YES: 6, Category.LOOKALIKE_NO: 5,
    Category.LOOKALIKE_CHOOSE: 3, Category.TWO_INTENTS: 6, Category.DIESEL_ENGINE_OPEN: 1,
    Category.DIESEL_ENGINE_CLOSED: 1, Category.PLAIN_YES: 6, Category.PLAIN_NO: 5, Category.CHOOSE_FOR_ME: 8,
    Category.QUESTION_DURING_QUESTION: 6, Category.BUTTON_TEXT: 5, Category.LANGUAGE_HYSTERESIS: 3,
    Category.NO_PENDING: 15, Category.PENDING_QUESTIONS: 15, Category.PENDING_CONFIRM_VARIANTS: 5,
    Category.PENDING_CONFIRM_COST: 5, Category.PENDING_CONFIRM_INTAKE: 5, Category.PENDING_LIMIT: 5,
    Category.GOLDEN: 8, Category.INTERPRETER_PATCH: 18, Category.PHRASES_WORD: 30, Category.PREPROD_MISS: 6,
}  # fmt: skip

_PENDING_CATEGORY: dict[PendingKind, Category] = {
    PendingKind.QUESTIONS: Category.PENDING_QUESTIONS,
    PendingKind.CONFIRM_VARIANTS: Category.PENDING_CONFIRM_VARIANTS,
    PendingKind.CONFIRM_COST: Category.PENDING_CONFIRM_COST,
    PendingKind.CONFIRM_INTAKE: Category.PENDING_CONFIRM_INTAKE,
    PendingKind.LIMIT: Category.PENDING_LIMIT,
}
_SOURCE_CATEGORY: dict[Source, Category] = {
    Source.GOLDEN: Category.GOLDEN,
    Source.PREPROD_MISS: Category.PREPROD_MISS,
}


def categories(case: Case, fixtures: Fixtures) -> set[Category]:
    """The coverage lines a case counts for: its tags, its open question's kind, its sources, words and patches."""
    found = set(case.tags)
    pending = fixtures.pendings.get(case.pending) if case.pending else None
    found.add(_PENDING_CATEGORY[pending.kind] if pending else Category.NO_PENDING)
    found |= {_SOURCE_CATEGORY[s] for s in case.sources if s in _SOURCE_CATEGORY}
    if case.words:
        found.add(Category.PHRASES_WORD)
    if case.patches:
        found.add(Category.INTERPRETER_PATCH)
    return found


def coverage_table(cases: Iterable[Case], fixtures: Fixtures) -> Counter[Category]:
    """Number of cases per coverage line."""
    return Counter(c for case in cases for c in categories(case, fixtures))


def check_set(cases: list[Case], fixtures: Fixtures) -> list[str]:
    """Every inconsistency between the cases and the fixtures, as readable lines (empty = consistent)."""
    problems = [f"duplicate id {i}" for i, n in Counter(c.id for c in cases).items() if n > 1]
    problems += _check_fixtures(fixtures)
    for case in cases:
        problems += _check_case(case, fixtures)
    return problems


def word_entries() -> set[str]:
    """Every "LIST:word" a case may name."""
    return {f"{name}:{w}" for name, words in WORD_LISTS.items() for w in words}


def _check_fixtures(fixtures: Fixtures) -> list[str]:
    problems: list[str] = []
    for name, pending in fixtures.pendings.items():
        case = fixtures.cases.get(pending.case)
        if case is None:
            problems.append(f"pending {name}: unknown case {pending.case}")
            continue
        if stray := pending.cars() - case.car_keys():
            problems.append(f"pending {name}: cars {sorted(stray)} not in {pending.case}")
        ids = pending.option_ids()
        if len(ids) != len(set(ids)):
            problems.append(f"pending {name}: duplicate option ids")
    ids = [p.id for p in fixtures.pendings.values()]
    problems += [f"pending id {i} used twice" for i, n in Counter(ids).items() if n > 1]
    return problems


def _check_case(case: Case, fixtures: Fixtures) -> list[str]:
    fixture = fixtures.cases.get(case.fixture)
    if fixture is None:
        return [f"{case.id}: unknown fixture {case.fixture}"]
    problems: list[str] = []
    if fixture.chat_language is not None and fixture.chat_language != case.lang:
        problems.append(f"{case.id}: chat language {fixture.chat_language} differs from lang {case.lang}")
    if case.expect.language != case.lang:
        problems.append(f"{case.id}: expected language {case.expect.language} differs from lang {case.lang}")
    problems += _check_pending(case, fixtures)
    problems += [f"{case.id}: unknown car {k}" for k in sorted(_car_keys(case) - fixture.car_keys())]
    problems += [f"{case.id}: unknown word entry {w}" for w in case.words if w not in word_entries()]
    problems += [
        f"{case.id}: word {w} not in the message" for w in case.words if w.partition(":")[2] not in case.message.lower()
    ]
    problems += [f"{case.id}: unknown interpreter.md patch {p}" for p in case.patches if p not in INTERPRETER]
    return problems


def _check_pending(case: Case, fixtures: Fixtures) -> list[str]:
    if case.pending is None:
        return []
    pending = fixtures.pendings.get(case.pending)
    if pending is None:
        return [f"{case.id}: unknown pending {case.pending}"]
    problems = [] if pending.case == case.fixture else [f"{case.id}: pending {case.pending} is not of {case.fixture}"]
    answer = case.expect.answer
    if answer and answer.pending_id != pending.id:
        problems.append(f"{case.id}: answer pending_id {answer.pending_id} is not {pending.id}")
    if answer and answer.option_id and answer.option_id not in pending.option_ids():
        problems.append(f"{case.id}: option {answer.option_id} not offered by {case.pending}")
    return problems


def _car_keys(case: Case) -> set[str]:
    e = case.expect
    keys = {k for g in e.goals for k in (g.focus_cars or [])}
    keys |= {r.car for r in e.rejections or []}
    if e.changes:
        keys |= set(e.changes.cars)
        keys |= {e.changes.prediction} if e.changes.prediction else set()
    return keys
