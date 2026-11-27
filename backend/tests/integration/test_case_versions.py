"""Spec 014 T111: the case store saves a version only on top of the version it was read at; a write based on a
stale read raises `VersionConflict` (a store failure stays `StoreUnavailable`)."""

import uuid

import pytest

from automind.chat.application.ports import StoreUnavailable, VersionConflict
from automind.chat.infrastructure.persistence.repositories import CaseRepo
from automind.shared.infrastructure import db


@pytest.fixture
async def repo() -> CaseRepo:
    await db.init_db()
    return CaseRepo()


async def test_a_save_on_a_stale_read_is_a_version_conflict(repo: CaseRepo) -> None:
    chat = str(uuid.uuid4())
    assert await repo.save_version(chat, {"depth": "QUICK"}, "hub", ["first"], expected=0) == 1
    stale, _, _ = await repo.latest(chat)  # a turn reads version 1 …
    assert await repo.save_version(chat, {"depth": "STANDARD"}, "user", ["panel edit"], expected=1) == 2  # … moved on
    with pytest.raises(VersionConflict) as conflict:
        await repo.save_version(chat, {"depth": "DEEP"}, "hub", ["from the stale read"], expected=stale)
    assert conflict.value.current == 2
    version, data, by = await repo.latest(chat)
    assert (version, data, by) == (2, {"depth": "STANDARD"}, "user")  # the stale write left nothing behind
    assert await repo.save_version(chat, {"depth": "DEEP"}, "hub", ["after a fresh read"], expected=version) == 3


async def test_a_save_ahead_of_the_store_is_a_conflict_too(repo: CaseRepo) -> None:
    chat = str(uuid.uuid4())
    with pytest.raises(VersionConflict) as conflict:
        await repo.save_version(chat, {}, "hub", [], expected=4)
    assert conflict.value.current == 0


def test_a_conflict_is_not_a_store_failure() -> None:
    assert not issubclass(VersionConflict, StoreUnavailable) and not issubclass(StoreUnavailable, VersionConflict)
