"""A settled user challenge becomes gold (spec 011 FR-003): `ChallengeGold.record` turns a CONFIRMED or CORRECTED
outcome into a gold value of origin `challenge` (`domain.choice.challenge_gold`) and writes it with the `challenges`
dataset's load. Errors: `GoldStoreUnavailable` passes through; nothing is written before the dataset is recorded."""

from __future__ import annotations

from automind.acquisition.gold.application.ports import GoldBook
from automind.acquisition.gold.domain.choice import CHALLENGES, challenge_gold
from automind.acquisition.gold.domain.config import GoldRules
from automind.acquisition.gold.domain.records import DatasetInfo

CHALLENGES_INFO = DatasetInfo(CHALLENGES, "User challenges (confirmed or corrected)", "challenge", "internal")


class ChallengeGold:
    """Gold from settled user challenges."""

    def __init__(self, book: GoldBook, rules: GoldRules) -> None:
        self._book = book
        self._rules = rules

    async def record(self, variant_id: str, attribute: str, outcome: str, value: str | float | None,
                     challenge_id: str | None, unit: str | None = None) -> bool:  # fmt: skip
        """Write the challenge's gold; False when the outcome or the value gives none."""
        gold = challenge_gold(variant_id, attribute, outcome, value, challenge_id, unit, self._rules)
        if gold is None:
            return False
        await self._book.record_load(CHALLENGES_INFO)
        await self._book.put(gold)
        return True
