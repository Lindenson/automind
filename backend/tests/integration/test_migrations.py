"""Alembic: head ↔ 0004 round trip on the dedicated migration database (spec 003 T007), and one round trip per
migration of spec 011 (T011: upgrade to the target, downgrade to its base, upgrade again)."""

import os
import subprocess

import pytest

from automind.config import settings

pytestmark = pytest.mark.skipif("automind_test" not in settings().database_url, reason="needs the local test DB")


def _alembic(*args: str) -> None:
    url = settings().database_url.replace("/automind_test", "/automind_mig")
    env = {**os.environ, "DATABASE_URL": url}
    subprocess.run(["alembic", *args], check=True, env=env, capture_output=True)


def migrate_roundtrip(target: str, base: str) -> None:
    """Upgrade to `target`, downgrade to `base`, upgrade to `target` again; then back to head."""
    _alembic("upgrade", target)
    _alembic("downgrade", base)
    _alembic("upgrade", target)
    _alembic("upgrade", "head")


def test_upgrade_downgrade_roundtrip():
    _alembic("upgrade", "head")
    _alembic("downgrade", "0004")
    _alembic("upgrade", "head")
    _alembic("check")


# spec 011: each migration task adds its (target, base) here
ROUNDTRIPS: list[tuple[str, str]] = [("0018", "0017"), ("0019", "0018"), ("0021", "0020")]


@pytest.mark.parametrize(("target", "base"), ROUNDTRIPS)
def test_migration_roundtrip(target, base):
    migrate_roundtrip(target, base)
