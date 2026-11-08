"""The verdict stored on every claim and used-price range (`claims.status`, `used_price_ranges.status`). Pure.

A claim is ACCEPTED, or REJECTED_<why>: the validator's reasons below, or a relevance verdict of the page
(`REJECTED_OTHER_VARIANT`, …) that the pipeline appends as `REJECTED_PREFIX + verdict`.
"""

from __future__ import annotations

from enum import StrEnum

REJECTED_PREFIX = "REJECTED_"


class ClaimStatus(StrEnum):
    """Whether a stored value may be used, and if not, why."""

    ACCEPTED = "ACCEPTED"
    REJECTED_UNSUPPORTED = "REJECTED_UNSUPPORTED"  # the quote is not on the page
    REJECTED_IMPLAUSIBLE = "REJECTED_IMPLAUSIBLE"  # outside the plausibility rules
    REJECTED_UNIT = "REJECTED_UNIT"  # a unit that cannot be converted
    REJECTED_OTHER_MARKET = "REJECTED_OTHER_MARKET"  # a price of another market
    REJECTED_OTHER_VARIANT = "REJECTED_OTHER_VARIANT"  # the page is about another version
    REJECTED_OTHER_YEAR = "REJECTED_OTHER_YEAR"  # a used price of another model year
