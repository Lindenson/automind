"""The life of a versioned engine object (a parser, a prompt, a rule override): `parsers.status`,
`prompt_versions.status`, `rule_overrides.status`. Pure.

    candidate ──► active ──► superseded        (a gate accepts the next version)
        │            └─────► degraded          (a parser whose yield dropped; the doctor proposes a successor)
        └──────────────────► rejected          (a gate rejects or a watch rolls back)
"""

from __future__ import annotations

from enum import StrEnum


class VersionStatus(StrEnum):
    """Where one version of an engine object is."""

    CANDIDATE = "candidate"  # proposed, not live (replay / shadow)
    ACTIVE = "active"  # live: the one version in use
    DEGRADED = "degraded"  # live but failing (parsers)
    SUPERSEDED = "superseded"
    REJECTED = "rejected"
