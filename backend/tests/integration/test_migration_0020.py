"""Spec 011 T052: migration 0020 (acq_tasks, acq_workers) round trip on the dedicated migration database.

Relative to 0020 itself, so the case stays valid when 0020 is rechained after 0018/0019.
"""

import os
import subprocess

import pytest

from automind.config import settings

pytestmark = pytest.mark.skipif("automind_test" not in settings().database_url, reason="needs the local test DB")


def _alembic(*args: str) -> None:
    url = settings().database_url.replace("/automind_test", "/automind_mig")
    env = {**os.environ, "DATABASE_URL": url}
    subprocess.run(["alembic", *args], check=True, env=env, capture_output=True)


def test_0020_roundtrip():
    _alembic("upgrade", "head")
    _alembic("downgrade", "0020-1")
    _alembic("upgrade", "head")
    _alembic("check")
