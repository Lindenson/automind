"""Shared · automind.shared.infrastructure.db: persistence of every area: the tables, the async session, migrations.

Owns:
- `models` — the SQLAlchemy models of all tables (catalogue, documents, evidence, claims, chats, turns, usage,
  registry, insight, engine…); split per area in S12.
- `session` — the async engine, `sessionmaker`, `init_db` and small chat-history helpers.
- `migrate` — runs the Alembic migrations programmatically (startup, tests, scripts/dev.sh).
Re-exports every public name of `models` plus `sessionmaker` and `init_db`, so callers write `db.<name>`.
Depends on: shared.infrastructure.config, SQLAlchemy, Alembic. Must not depend on: chat, acquisition, observability,
delivery.
Public API: the re-exported names; `__all__` lists exactly what `from ... import *` exported before it existed.
"""

from automind.shared.infrastructure.db.models import *  # noqa: F403
from automind.shared.infrastructure.db.models import Base, now, uid  # noqa: F401
from automind.shared.infrastructure.db.session import init_db, sessionmaker  # noqa: F401

__all__ = sorted(name for name in dir() if not name.startswith("_"))  # = the default star export
