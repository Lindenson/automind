"""Acquisition · acquisition.domain: the engine's pure rules — no database, network or model calls.

Owns:
  `relevance` — is a page about the exact requested variant; `relevance_audit` — rejections later contradicted.
  `plausibility` — value ranges and cross-attribute checks; `sense_ev` — meaning rules for electric values.
  `physics` — physical consistency of one variant's values; `agreement` — agreement of source families on a value.
  `blame` — vector blame: which component made a wrong value wrong; `replacement` — a shown value later replaced.
  `replay` — replay comparison against gold and the report; `drift` — parser drift detectors.
  `gates` — verdicts of the replay, shadow and watch gates; `thompson` — exploration by Thompson sampling.
Depends on: shared.evidence only.
Must not depend on:
  I/O and frameworks (sqlalchemy, httpx, fastapi, langchain, langgraph, prometheus_client), shared.infrastructure,
  chat.application / dialog / infrastructure, infrastructure.search / retention / overrides
  (import-linter acquisition-domain-pure).
  plausibility, sense_ev and relevance are also used by the chat (domain-pure).
Public API: the modules in __all__ (callers import from them).
Note: the I/O side of `drift` lives in acquisition.drift. (`served` and `versions` moved to shared.provenance in
  spec 012 S4.)
"""

__all__: list[str] = [
    "agreement",
    "blame",
    "drift",
    "gates",
    "physics",
    "plausibility",
    "relevance",
    "relevance_audit",
    "replacement",
    "replay",
    "sense_ev",
    "thompson",
]
