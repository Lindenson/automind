"""Acquisition · acquisition.gold.application: gold's services behind their ports.

Owns:
  `ports` — GoldBook, Candidates, DatasetReader, ReferenceSet, GoldSource (+ Harvest); one `GoldStoreUnavailable`.
  `load` — GoldLoad: a source's gold for the variants replaces its previous load; the sources DatasetGold (rows
    matched per variant) and ReferenceGold (the entries naming a variant).
  `challenges` — ChallengeGold: a confirmed or corrected user challenge becomes gold.
Flow: gold.infrastructure.wiring builds each service over the stores and loaders; the rules are in gold.domain.
Depends on: gold.domain, shared.contracts.
Must not depend on: gold.infrastructure, sqlalchemy, httpx, shared.infrastructure (storage and HTTP only through the
  ports); as acquisition/__init__ (registry-no-chat).
Public API: the modules in __all__ (callers import from them).
"""

__all__: list[str] = ["challenges", "load", "ports"]
