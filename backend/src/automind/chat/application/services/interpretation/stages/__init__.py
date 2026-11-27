"""Chat · chat.application.services.interpretation.stages: the named steps of applying one message to the case.

Owns: `picked_option` (a tapped option), `make_to_choose` (a make the candidates come from, the car replaced),
  `cars_safety_net` (two named cars are a comparison), `brand_explained` (a brand the person explains),
  `heard_rejections` (a rejection of the model's reading kept only with the person's words and the car's value,
  spec 013 S2), `person_facts` (region, distance, charging, body, new or used), `stated_energy` (the person's
  consumption figures), `understood` (the pending question answered or not).
Flow: called by `service.InterpretationService.apply`, in that order (the option or the delta first).
Depends on: chat.domain (case, intake, identification, understanding), shared.contracts, the package's `contracts`.
Must not depend on: chat.dialog, the model, storage.
Public API: the modules in __all__.
"""

__all__ = ["brand_explained", "cars_safety_net", "heard_rejections", "make_to_choose", "person_facts", "picked_option",
           "stated_energy", "understood"]  # fmt: skip
