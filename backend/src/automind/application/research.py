"""Moved into the acquisition engine (spec 011 strangler S1–S7: `acquisition/pipeline/*`, `acquisition/read.py`).

Only `application/challenge.py` and `application/repair.py` still read the research-time rules here; T048 gives them
`acquisition.api` and T049 deletes this module.
"""

from automind.acquisition.pipeline.job import area_hits
from automind.acquisition.pipeline.merge import reselect
from automind.acquisition.pipeline.validate import ReaderClaim, check, known_values, plausibility_ctx, sense_before
from automind.domain import specs

__all__ = ["ReaderClaim", "area_hits", "check", "known_values", "plausibility_ctx", "reselect", "sense_before", "specs"]
