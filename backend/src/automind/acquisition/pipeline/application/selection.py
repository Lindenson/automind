"""The merge stage (spec 011 R5): a variant's selected values recomputed from all its accepted claims, and its
gearbox from unanimous transmission claims.

Errors: `PipelineStoreUnavailable` from the value store propagates. The gearbox is set before the values are
selected, each in its own transaction: a failure between them leaves the old values, which the next reselect
replaces (the gearbox only fills an empty column, so repeating it is harmless)."""

from __future__ import annotations

from automind.acquisition.pipeline.application.ports import ValueStore
from automind.acquisition.pipeline.domain import selection

VERSION = "merge@1"


class ValueSelection:
    """Selected values and gearbox of a variant over the value store."""

    def __init__(self, values: ValueStore) -> None:
        self.values = values

    async def reselect(self, variant_id: str) -> None:
        """Recompute the selected values of every attribute from the accepted claims (spec 002 FR-017/FR-018); a
        variant without a gearbox first gets it from unanimous transmission claims (spec 004 FR-028)."""
        await self.fill_gearbox(variant_id)
        await self.values.replace_selected(variant_id, selection.select_values)

    async def fill_gearbox(self, variant_id: str) -> None:
        """At least two accepted transmission claims that agree give the variant its gearbox (when it has none)."""
        family = selection.unanimous_gearbox(await self.gearboxes(variant_id))
        if family is not None:
            await self.values.set_gearbox(variant_id, family)

    async def gearboxes(self, variant_id: str) -> list[str]:
        """Gearbox families of the variant's accepted transmission claims."""
        return selection.gearbox_families(await self.values.accepted_transmissions(variant_id))

    async def gearboxes_mixed(self, variant_id: str) -> bool:
        """The accepted transmission claims name gearboxes that contradict each other."""
        return selection.mixed_families(await self.gearboxes(variant_id))
