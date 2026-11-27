"""Spec 015 T220, T224, T225: the policy's passes in `policy_decisions` — a pass written again replaces its row, the
config is stored once per hash, a read pass replays to the same decision, old passes are pruned after 90 days and a
deleted chat takes its passes along."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update
from tests.unit.chat.dialog.policy.builder import config, situation

from automind.chat.dialog.policy import config_json, decide, record_of, replay
from automind.chat.domain.case import CaseCar, CaseFile
from automind.chat.domain.decision import CarState, DecisionRecord, PolicyConfig
from automind.chat.infrastructure.persistence.decisions import KEEP_DAYS, DecisionRepo
from automind.chat.infrastructure.persistence.repositories import ChatRepo
from automind.chat.infrastructure.retention import prune_decisions
from automind.shared.infrastructure import db
from automind.shared.infrastructure.db.models import PolicyDecisionRow
from automind.shared.infrastructure.db.session import sessionmaker

CASE = CaseFile(cars=[CaseCar(key="car#1", request_text="golf", make="Volkswagen", model="Golf", variant_id="v1",
                              resolution="CONFIRMED", condition="NEW")])  # fmt: skip
STALE = {"car#1": CarState(in_catalog=True, data_fresh=False, plausible_generations=1)}


@pytest.fixture
async def repo() -> DecisionRepo:
    await db.init_db()
    return DecisionRepo()


def _record(chat: str, turn: str, pass_no: int, cost: float = 0.5) -> DecisionRecord:
    s = situation(CASE, "compare", STALE, cost_estimate_eur=cost, pass_no=pass_no)
    return record_of(decide(s, config()), s, config(), chat_id=chat, turn_id=turn, case_version=3)


async def test_a_turn_reads_back_its_passes_and_replays_them(repo: DecisionRepo) -> None:
    chat, turn = str(uuid.uuid4()), str(uuid.uuid4())
    await repo.record(_record(chat, turn, 2), config_json(config()))
    await repo.record(_record(chat, turn, 1, cost=0.1), config_json(config()))
    await repo.record(_record(chat, turn, 1, cost=0.05), config_json(config()))  # pass 1 again: replaces its row
    passes = await repo.for_turn(turn)
    assert [p.pass_no for p in passes] == [1, 2]
    assert passes[0] == _record(chat, turn, 1, cost=0.05) and passes[1] == _record(chat, turn, 2)
    stored = await repo.config(passes[1].config_hash)
    assert stored is not None and PolicyConfig.model_validate(stored) == config()
    assert replay(passes[1], CASE, PolicyConfig.model_validate(stored)).action.kind == passes[1].action["kind"]
    assert await repo.for_turn(str(uuid.uuid4())) == [] and await repo.config("nope") is None


async def test_passes_older_than_90_days_are_pruned(repo: DecisionRepo) -> None:
    chat, old, new = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    await repo.record(_record(chat, old, 1), config_json(config()))
    await repo.record(_record(chat, new, 1), config_json(config()))
    async with sessionmaker()() as s:
        long_ago = datetime.now(UTC) - timedelta(days=KEEP_DAYS + 1)
        await s.execute(update(PolicyDecisionRow).where(PolicyDecisionRow.turn_id == old).values(created_at=long_ago))
        await s.commit()
    assert await prune_decisions(repo) >= 1
    assert await repo.for_turn(old) == [] and len(await repo.for_turn(new)) == 1


async def test_a_deleted_chat_takes_its_passes_along(repo: DecisionRepo) -> None:
    chat, turn = str(uuid.uuid4()), str(uuid.uuid4())
    await repo.record(_record(chat, turn, 1), config_json(config()))
    counts = await ChatRepo().delete(chat)
    assert counts["policy_decisions"] == 1 and await repo.for_turn(turn) == []
