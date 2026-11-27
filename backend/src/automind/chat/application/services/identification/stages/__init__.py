"""Chat · chat.application.services.identification.stages: the named steps of identifying one car.

Owns: `normalise_name` (URL, make and model spellings), `catalogue_lookup` (the models known for the make),
  `ask_model` (the make's models offered), `place_market` (where the car is sold), `year_first` (a used car's
  year), `narrow_ladder` (one ladder step over a pool of versions), `ask_stale_version` (old catalogue rows and the
  registered versions), `offer_engines` (the engines there are), `verify_proposal` (a version found checked
  against the person's words, spec 013 I2), `change_tactic` (after a rejection a dead end widens, spec 013 T024),
  `settle` (the outcome recorded on the car).
Flow: called by `service.IdentificationService.run` and the strategies, in the order of the service.
Depends on: chat.domain, chat.application.ports, the package's `contracts`, `catalogue`, `versions`.
Must not depend on: chat.dialog, the strategies.
Public API: the modules in __all__.
"""

__all__ = ["ask_model", "ask_stale_version", "catalogue_lookup", "change_tactic", "narrow_ladder", "normalise_name",
           "offer_engines", "place_market", "settle", "verify_proposal", "year_first"]  # fmt: skip
