"""Spec 013 T004: the golden message set loads, is consistent with its fixtures and covers what T004 asks for.

No DB, no model: the set itself is under test (T005 runs it on the interpreter).
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import get_args

import pytest

from automind.chat.dialog import phrases
from automind.chat.domain.decision import ActionKind as DomainActionKind
from tests.eval.understanding.coverage import (
    CASES_MAX,
    CASES_MIN,
    DIESEL,
    INTERPRETER,
    INTERPRETER_VERSION,
    LANG_MIN_SHARE,
    PROBLEM_TABLE,
    REQUIRED,
    SPEC1_MESSAGES,
    WORD_LISTS,
    categories,
    check_set,
    coverage_table,
    word_entries,
)
from tests.eval.understanding.fixture_models import Fixtures, load_fixtures
from tests.eval.understanding.schema import Case, load_cases
from tests.eval.understanding.vocab import NEW_ACTION_KINDS, ActionKind, AnswerKind, Category, Lang, PendingKind

PROMPT = Path(phrases.__file__).parent / "prompts" / "interpreter.md"


@pytest.fixture(scope="module")
def fixtures() -> Fixtures:
    return load_fixtures()


@pytest.fixture(scope="module")
def cases() -> list[Case]:
    return load_cases()


def test_size_and_consistency(cases: list[Case], fixtures: Fixtures) -> None:
    assert CASES_MIN <= len(cases) <= CASES_MAX
    assert check_set(cases, fixtures) == []


def test_languages_roughly_even(cases: list[Case]) -> None:
    per_lang = Counter(c.lang for c in cases)
    assert set(per_lang) == set(Lang)
    assert all(n / len(cases) >= LANG_MIN_SHARE for n in per_lang.values()), per_lang


def test_every_required_category(cases: list[Case], fixtures: Fixtures) -> None:
    table = coverage_table(cases, fixtures)
    short = {c.value: (table[c], need) for c, need in REQUIRED.items() if table[c] < need}
    assert short == {}, "category: (cases, required)"


def test_every_pending_kind_in_every_language(cases: list[Case], fixtures: Fixtures) -> None:
    seen = {(fixtures.pendings[c.pending].kind, c.lang) for c in cases if c.pending}
    assert {(k, lang) for k in PendingKind for lang in Lang} - seen == set()


def test_spec_examples_and_problem_table(cases: list[Case]) -> None:
    tagged = {c.message for c in cases if Category.SPEC1 in c.tags}
    assert set(SPEC1_MESSAGES) - tagged == set()
    in_table = {c.message for c in cases if Category.PROBLEM_TABLE in c.tags}
    assert set(PROBLEM_TABLE) - in_table == set()


def test_diesel_twice_open_and_not_open(cases: list[Case], fixtures: Fixtures) -> None:
    diesel = [c for c in cases if c.message == DIESEL]
    open_q = [c for c in diesel if c.pending and fixtures.pendings[c.pending].items[0].topic == "ENGINE"]
    closed = [c for c in diesel if c.pending is None]
    assert len(open_q) == 1 and len(closed) == 1
    opened, shut = open_q[0].expect, closed[0].expect
    assert opened.answer is not None and opened.answer.kind is AnswerKind.VALUE
    assert shut.answer is None and shut.goals == []
    for e in (opened, shut):
        assert e.changes is not None and any(car.fuel == "diesel" for car in e.changes.cars.values())


def test_every_phrases_word_is_a_case(cases: list[Case]) -> None:
    covered = {w for c in cases for w in c.words}
    assert word_entries() - covered == set()


def test_word_lists_frozen_match_the_module() -> None:
    live = {"YES": phrases._YES, "NO": phrases._NO, "CHOOSE": phrases._CHOOSE, "GO": phrases._GO}
    assert {k: set(v) for k, v in live.items()} == {k: set(v) for k, v in WORD_LISTS.items()}, (
        "a word list changed: add its cases (spec 013 T004) and update coverage.WORD_LISTS"
    )


def test_every_interpreter_patch_is_a_case(cases: list[Case]) -> None:
    covered = {p for c in cases for p in c.patches}
    assert set(INTERPRETER) - covered == set()


def test_interpreter_prompt_version_is_the_covered_one() -> None:
    first = PROMPT.read_text(encoding="utf-8").splitlines()[0]
    assert INTERPRETER_VERSION in first, "interpreter.md changed: turn its new rules into cases, then bump the version"


def test_action_kinds_follow_the_domain() -> None:
    domain = set(get_args(DomainActionKind))
    assert {a.value for a in ActionKind} - {a.value for a in NEW_ACTION_KINDS} == domain


def test_categories_are_derived_from_the_fixture(cases: list[Case], fixtures: Fixtures) -> None:
    first = next(c for c in cases if c.pending is None)
    assert Category.NO_PENDING in categories(first, fixtures)
