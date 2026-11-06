"""Chat · chat.application.services.identification.strategies: the ways to identify a placed car, tried in order
until one answers (`contracts.Fallback`; spec 008 FR-020: sourced first).

Owns: `sourced_versions` — `SourcedVersions`, the ladder over the versions sources list; `catalogue_rows` —
  `CatalogueRows`, the ladder over the catalogue's rows, less certain; `open_world` — `OpenWorld`, the resolver
  with sources, less certain (always answers).
Flow: `service.IdentificationService` builds them in that order; None hands the car to the next.
Depends on: the package's stages, `catalogue`, `assessment`, `resolver`, `versions`.
Must not depend on: chat.dialog, the service.
Public API: the modules in __all__.
"""

__all__ = ["catalogue_rows", "open_world", "sourced_versions"]
