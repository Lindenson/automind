"""Alembic: head ↔ 0004 round trip on the dedicated migration database (spec 003 T007)."""

import os
import subprocess

import pytest

from automind.config import settings

pytestmark = pytest.mark.skipif("automind_test" not in settings().database_url, reason="needs the local test DB")


def _alembic(*args: str) -> None:
    url = settings().database_url.replace("/automind_test", "/automind_mig")
    env = {**os.environ, "DATABASE_URL": url}
    subprocess.run(["alembic", *args], check=True, env=env, capture_output=True)


def test_upgrade_downgrade_roundtrip():
    _alembic("upgrade", "head")
    _alembic("downgrade", "0004")
    _alembic("upgrade", "head")
    _alembic("check")
