"""Graph-test fixtures: real Postgres (automind_test) + checkpointer, fake LLM, fixture search."""

import uuid
from datetime import UTC, datetime

import pytest

from automind.acquisition.engine import Engine
from automind.acquisition.ports import AcqPorts
from automind.chat.application.ports import Ports
from automind.chat.dialog.prompts import load_all
from automind.chat.infrastructure.checkpoint import checkpointer
from automind.chat.infrastructure.events import EventBus
from automind.chat.infrastructure.models_on_sale import models_on_sale
from automind.chat.infrastructure.persistence.repositories import (
    CaseRepo,
    EventRepo,
    FeasibilityRepo,
    JobRepo,
    MarketFactRepo,
    MessageRepo,
    TurnRepo,
)
from automind.shared.infrastructure.config.loader import reference
from automind.shared.infrastructure.db import init_db
from automind.shared.metering.usage import Limits, Prices, TurnBudget
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
    """Chat ports with the engine bound to the same model, reference data and market facts (as live_ports does);
    `search` is the engine's searcher and, for fixture searches, its page store too."""
    llm = llm or FakeLLM()
    ref = open_web_reference()
    facts = MarketFactRepo()
    acq = AcqPorts(llm=llm, ref=ref, search=search, market_facts=facts)
    return Ports(
        llm=llm,
        acquisition=Engine(acq),
        cases=CaseRepo(),
        turns=TurnRepo(),
        events=events or EventBus(EventRepo()),
        jobs=JobRepo(),
        clock=FixedClock(),
        ref=ref,
        messages=MessageRepo(),
        estimator=FixedEstimator(),
        feasibility=FeasibilityRepo(),
        market_facts=facts,
        models_on_sale=models_on_sale,
    )


def engine(ports: Ports) -> AcqPorts:
    """The engine's ports behind the chat's (search, page store, readers, registry, reference data)."""
    return ports.acquisition.ports  # type: ignore[union-attr]


def share(ports: Ports, **values) -> None:  # noqa: ANN003
    """Set shared parts (ref, registry, llm, market_facts) on the chat's ports and the engine's alike."""
    for k, v in values.items():
        setattr(ports, k, v)
        setattr(engine(ports), k, v)


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


async def forget_make(make: str) -> None:
    """Hide a make's catalog rows and line-up left by earlier tests (spec 005 open-world scenarios): the variants
    are renamed to a throw-away make (they are referenced from research tables), the line-up is deleted."""
    from sqlalchemy import delete, update

    from automind.shared.infrastructure import db

    async with db.sessionmaker()() as s:
        hidden = {
            "make": f"old-{uuid.uuid4().hex[:8]}",
            "canonical_key": db.Variant.canonical_key + "#" + db.Variant.id,
        }
        await s.execute(update(db.Variant).where(db.Variant.make == make).values(**hidden))
        await s.execute(delete(db.BrandLineup).where(db.BrandLineup.make == make))
        await s.commit()
