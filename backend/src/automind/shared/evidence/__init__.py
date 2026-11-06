"""Shared · shared.evidence: the evidence rules every value passes — where it comes from, whether its quote is on
the page, and which value wins among several claims; plus `sense` (does a value mean what its attribute means).

Owns: `sources` — source policy, source type, official domains, provenance class; `excerpts` — verbatim excerpt
  checks; `selection` — agreement, majority and confidence of selected values; `sense` — meaning checks.
Depends on: shared.vehicle (attribute registry). Must not depend on: any area, sqlalchemy, httpx, langchain.
Public API: the names below (`from automind.shared import evidence; evidence.select_value(...)`) and `sense`.
"""

from automind.shared.evidence.excerpts import (
    MAX_GAP_CHARS,
    occurs,
    validate_excerpt,
)
from automind.shared.evidence.selection import (
    MAJORITY_OVER_AUTHORITY,
    ClaimIn,
    Selected,
    select_all,
    select_value,
    sibling_code,
    variant_match_uncertain,
)
from automind.shared.evidence.sources import (
    AUTHORITY,
    RULES_VERSION,
    SourcePolicy,
    assign_provenance,
    classify_source,
    configure,
    domain_of,
    is_denied,
    is_official,
    policy,
    registrable_name,
)

__all__ = [
    "AUTHORITY",
    "ClaimIn",
    "MAJORITY_OVER_AUTHORITY",
    "MAX_GAP_CHARS",
    "RULES_VERSION",
    "Selected",
    "SourcePolicy",
    "assign_provenance",
    "classify_source",
    "configure",
    "domain_of",
    "is_denied",
    "is_official",
    "occurs",
    "policy",
    "registrable_name",
    "select_all",
    "select_value",
    "sibling_code",
    "validate_excerpt",
    "variant_match_uncertain",
    "sense",
]
