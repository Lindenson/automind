import os
from pathlib import Path

# Tests use their own database: TEST_DATABASE_URL (scripts/check.sh sets it to the Docker Postgres,
# database automind_test) or, without it, the embedded development server in ./.pgdata.
_pg = Path(__file__).resolve().parents[2] / ".pgdata" / "pg"
os.environ["DATABASE_URL"] = (
    os.environ.get("TEST_DATABASE_URL") or f"postgresql+asyncpg://postgres@/automind_test?host={_pg}"
)

import pytest  # noqa: E402

from automind.infrastructure.config import configure_domain  # noqa: E402

configure_domain()


@pytest.fixture
def no_network():
    """Spec 011 T008: any network call in the test raises NetworkForbidden; the guard counts attempts."""
    from automind.acquisition.replay.offline import no_network as guard  # noqa: PLC0415

    with guard() as g:
        yield g


def pytest_addoption(parser):
    parser.addoption("--record", action="store_true", default=False, help="record golden cassettes (live mode)")
