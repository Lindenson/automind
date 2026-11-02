"""Graph-test fixtures: real Postgres (automind_test) + checkpointer, fake LLM, fixture search."""

import uuid
from datetime import UTC, datetime

import pytest

from automind.application.ports import Ports
from automind.application.usage import Limits, Prices, TurnBudget
from automind.infrastructure.checkpoint import checkpointer
from automind.infrastructure.config import reference
from automind.infrastructure.db import init_db
from automind.infrastructure.db.repositories import CaseRepo, EventRepo, FeasibilityRepo, JobRepo, MessageRepo, TurnRepo
from automind.infrastructure.events import EventBus
from automind.orchestration.prompts import load_all
from tests.fakes.fake_llm import FakeLLM, FixedEstimator

PRICES = Prices(llm={}, default_llm=(1.0, 4.0), eur_per_credit=0.0074, credits={"search_advanced": 2})


class FixedClock:
    def now(self):
        return datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="session")
async def migrated():
    await init_db()
    return True


@pytest.fixture
async def saver(migrated):
    async with checkpointer() as cp:
        yield cp


@pytest.fixture
def chat_id():
    return str(uuid.uuid4())


def make_ports(llm=None, search=None, events=None) -> Ports:
    return Ports(
        llm=llm or FakeLLM(),
        search=search,
        cases=CaseRepo(),
        turns=TurnRepo(),
        events=events or EventBus(EventRepo()),
        jobs=JobRepo(),
        clock=FixedClock(),
        ref=open_web_reference(),
        messages=MessageRepo(),
        estimator=FixedEstimator(),
        feasibility=FeasibilityRepo(),
    )


def open_web_reference(**overrides):
    """Reference data for fixture scenarios: no favourites, so round 0 uses the open-web templates the
    fixtures match on (favourite planning has its own tests). Overrides replace fields, e.g. favourites=[...]."""
    from dataclasses import replace

    return replace(reference(load_all()), **{"favourites": [], "favourite_queries": {}, **overrides})


def budget_factory(**limits):
    def make(chat_id, turn_id):
        return TurnBudget(chat_id=chat_id, turn_id=turn_id, prices=PRICES, limits=Limits(**limits))

    return make


@pytest.fixture
def messages():
    return MessageRepo()
