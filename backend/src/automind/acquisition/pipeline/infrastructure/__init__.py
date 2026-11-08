"""Acquisition · acquisition.pipeline.infrastructure: the stores behind the pipeline's ports, and their wiring.

Owns: `variant_store` (`vehicle_variants` read as `CarVariant`), `evidence_store` (`documents`, `evidence` and a
  page's rows: claims, maintenance, reviews, issues, reliability stats, brand facts, used prices, residual values),
  `value_store` (`spec_values`, accepted claims, the variant's gearbox), `verdict_store` (`page_relevance`),
  `job_book` (`research_jobs` metrics, `research_runs`), `area_sources` (the sources of an area's accepted
  values), `wiring` (`stores()`, `value_selection()`).
Depends on: acquisition.pipeline.application (the ports), acquisition.pipeline.domain, shared.infrastructure.db.
Public API: the modules in __all__.
"""

__all__ = ["area_sources", "evidence_store", "job_book", "value_store", "variant_store", "verdict_store", "wiring"]
