"""Who was wrong when a shown value was wrong (spec 010 FR-017), kept for its callers. Pure.

Spec 011 replaced it by the vector blame of `acquisition/domain/blame.py` (research R9); this is the top component of
that vector under the 010 labels. If the stored excerpt holds the corrected value, the page said the right thing and
our reading was wrong (site reader or model extraction); otherwise the source said the wrong thing.
"""

from __future__ import annotations

from automind.acquisition.domain.blame import LABEL_010, BlameCase, blame_vector, numbers


def blame(corrected: str | None, excerpt: str | None, extracted_by: str | None) -> str:
    if not corrected or not excerpt:
        return "source"
    want = tuple(sorted(numbers(corrected)))
    if not want:
        return "source"
    case = BlameCase(
        attribute=None,
        claim_value=None,
        truth=None,
        truth_alternatives=want,
        tolerance=("abs", 0.0),
        producer="reader" if (extracted_by or "").upper() == "READER" else "extractor",
        excerpt=excerpt,
    )
    return LABEL_010[blame_vector(case).top()]
