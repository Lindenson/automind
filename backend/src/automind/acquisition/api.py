"""The acquisition engine's public interface (spec 011, contracts/acquire.md).

The only engine module the chat (`automind.application`, `automind.orchestration`, `automind.domain`) may import
(FR-005, FR-006). The chat orders data here — "these kinds of data for this car, by this deadline" — and receives
values with confidence and sources, and for gaps the sources tried. Live calls run in the caller's process within
the caller's deadline and budget (research R5); background work runs in the worker. Everything else under
`automind.acquisition` is internal. Functions are added here only, task by task.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from automind.acquisition.domain import blame as _blame
from automind.acquisition.gold import repo as _gold

__all__: list[str] = ["ChallengeBlame", "blame_challenge", "record_challenge_gold"]


async def record_challenge_gold(
    variant_id: str, attribute: str, outcome: str, value: str | float | None, unit: str | None = None,
    challenge_id: str | None = None,
) -> bool:  # fmt: skip
    """A user challenge that ended CONFIRMED (the shown value) or CORRECTED (the newly selected value) becomes gold:
    origin `challenge`, rule `challenge_confirmed`/`challenge_corrected`, confidence MEDIUM (spec 011 FR-003).
    Returns whether a gold value was written."""
    return await _gold.record_challenge(variant_id, attribute, outcome, value, challenge_id, unit)


@dataclass(frozen=True)
class ChallengeBlame:
    """Who erred when a challenged value was wrong (spec 011 FR-011, research R9)."""

    label: str  # the 010 label of the top component (truth_signals.blame)
    vector: dict[str, float]  # shares per component, sum 1
    components: dict[str, str] = field(default_factory=dict)  # component -> its key (km77@v1, ...)
    disputed: bool = False


async def blame_challenge(
    corrected: str | None, excerpt: str | None, extracted_by: str | None, claim_id: str | None = None
) -> ChallengeBlame:
    """Vector blame of one claim a challenge found wrong. `extracted_by` is the claim's READER/LLM, or
    `LLM_EXCERPT` when the claim's quote is not on its page (our extraction invented it). The claim's producer
    version and model name the blamed parser or extractor."""
    version = model = None
    domain = ""
    if claim_id:
        from automind.infrastructure.db import Claim, Evidence, sessionmaker  # noqa: PLC0415

        async with sessionmaker()() as s:
            c = await s.get(Claim, claim_id)
            if c is not None:
                version, model = c.producer_version, c.model
                e = await s.get(Evidence, c.evidence_id)
                domain = e.domain if e is not None else ""
    producer = "reader" if (extracted_by or "").upper() == "READER" else "extractor"
    if (extracted_by or "").upper() == "LLM_EXCERPT":
        b = _blame.Blame({"extractor": 1.0}, "extractor")
    elif not corrected or not excerpt or not _blame.numbers(corrected):
        b = _blame.Blame({"source": 1.0}, "source")
    else:
        b = _blame.blame_vector(
            _blame.BlameCase(
                attribute=None,
                claim_value=None,
                truth=None,
                tolerance=("abs", 0.0),
                truth_alternatives=tuple(sorted(_blame.numbers(corrected))),
                producer=producer,
                producer_version=version,
                model=model,
                excerpt=excerpt,
                domain=domain,
            )  # fmt: skip
        )
    case = _blame.BlameCase(attribute=None, claim_value=None, truth=None, producer=producer,
                            producer_version=version, model=model, domain=domain)  # fmt: skip
    return ChallengeBlame(_blame.LABEL_010[b.top()], dict(b.vector), _blame.component_keys(case, b), b.disputed)
