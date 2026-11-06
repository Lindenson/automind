"""Shared · automind.shared.infrastructure: the technical services every area uses: config, database, LLM gateway.

Owns:
- `config` — settings from the environment (.env) and the loaders of config/*.yaml.
- `db` — the SQLAlchemy models of all tables (until the S12 split per area), the async session, migrations.
- `llm` — the LLM gateway (the one place that creates chat models) and the usage callback that charges every call.
Depends on: shared kernel packages, pydantic-settings, SQLAlchemy, Alembic, LangChain.
Must not depend on: chat, acquisition, delivery (target `shared-is-kernel`); observability (leaf area).
Note: config.loader still assembles `Reference` from chat and engine modules (untangled in S4); llm imports
acquisition (served calls, overrides), the chat UsageRepo and observability metrics.
Public API: the subpackages in __all__ (callers import from their modules).
"""

__all__ = ["config", "db", "llm"]
