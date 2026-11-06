"""Observability · automind.observability.domain: pure rules for judging turns and turning failures into issues.

Owns:
- `outcome` — `TurnFacts` → failure classes and a 0..1 score (an explicit rating wins).
- `clusters` — `Failure`, `Group`: failures with the same key form a group; stable fingerprint per issue.
- `impact` — the impact of an issue and the top list.
- `levers` — `check_fix`: a config fix only for a declared file and existing key path, otherwise a code fix.
- `issue_text` — `copy_text`: the "copy for Claude Code" task of an issue, untrusted text fenced as quotes.
Depends on: the standard library only. Must not depend on: any I/O library (SQLAlchemy, httpx, FastAPI, LangChain,
prometheus_client), observability.application/infrastructure/metrics, chat, acquisition, delivery
(import contract `insight-domain-pure`).
Public API: the modules in __all__ (callers import from them).
"""

__all__ = ["clusters", "impact", "issue_text", "levers", "outcome"]
