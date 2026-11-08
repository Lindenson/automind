"""Acquisition · acquisition.gold: gold (reference) values from open datasets, the reference set and user challenges.

Owns:
  `domain` — records, matching of dataset rows to a catalogue variant, the reference-set rule, which gold counts.
  `application` — GoldLoad (a source's gold replaces its previous load), ChallengeGold; their ports.
  `infrastructure` — the gold and candidate stores, the open-data loaders, the reference file, wiring.
Flow: delivery.cli.gold → wiring.gold_load() → GoldLoad.run: source.harvest (loader rows → domain.match) → GoldStore.
  Readers of gold (reputation, replay) use `wiring.gold_store().best(variant_id)`; tolerances `wiring.gold_rules()`.
Depends on: parsing.normalise (fuel), infrastructure.config, shared (contracts, infrastructure, vehicle).
Must not depend on: as acquisition/__init__ (registry-no-chat).
Public API: the packages in __all__ (callers import from their modules).
"""

__all__: list[str] = ["application", "domain", "infrastructure"]
