"""Shared · automind.shared: the kernel both the chat and the acquisition engine speak.

Owns:
- `vehicle` — exact identity, spec attributes, units, the make registry.
- `evidence` — source typing, excerpt checks, provenance, value selection, sense checks.
- `research_order` — what to research for which car (areas, gaps) and the search queries for it.
- `contracts` — protocols and value types both areas use (reference data, LLM, web documents, site readers).
- `metering` — per-turn usage budget and limits.
- `infrastructure` — config loading and settings, the database (models, session, migrations), the LLM gateway.
Depends on: the standard library, pydantic, SQLAlchemy and LangChain (infrastructure only).
Must not depend on: chat, acquisition, delivery (target contract `shared-is-kernel`); observability (leaf area).
Note: not yet true — vehicle.identity imports chat.domain lazily; infrastructure.config.loader assembles `Reference`
from chat and engine modules; infrastructure.llm uses acquisition (served calls, overrides), the chat UsageRepo and
observability metrics (untangled in S4 and later steps).
Public API: the subpackages in __all__ (callers import from their modules).
"""

__all__ = ["contracts", "evidence", "infrastructure", "metering", "research_order", "vehicle"]
