"""The `ResearchHistory` port over the engine's read model (`acquisition.api`): what earlier research left per
catalogue version. A database failure becomes `StoreUnavailable`."""

from __future__ import annotations

from datetime import datetime

from automind.acquisition import api as acquisition
from automind.chat.infrastructure.persistence.errors import store_errors


class EngineResearchHistory:
    """Reads the engine's research runs and versions (no network, no model call)."""

    @store_errors
    async def powertrains(self, variant_ids: list[str]) -> dict[str, str | None]:
        return await acquisition.powertrains(variant_ids)

    @store_errors
    async def last_done(self, variant_ids: list[str]) -> dict[str, dict[str, datetime]]:
        return await acquisition.last_done(variant_ids)

    @store_errors
    async def unmet_areas(self, variant_ids: list[str]) -> dict[str, set[str]]:
        return await acquisition.unmet_areas(variant_ids)

    @store_errors
    async def registry_done(self, variant_ids: list[str]) -> dict[str, dict[str, datetime]]:
        return await acquisition.registry_done(variant_ids)
