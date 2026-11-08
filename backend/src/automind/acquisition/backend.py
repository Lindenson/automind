"""The engine behind `acquisition.api`: one object that implements the api's `Backend` protocol (spec 012 T027).

`acquisition.api` is the only engine module the chat may import, and it imports nothing of the engine. It reaches
the engine through `Backend`, implemented here by delegating to the engine's modules; mypy checks this class
against the protocol, so the facade is typed end to end without `type: ignore`.
"""

from __future__ import annotations

from typing import Any

from automind.acquisition import car_data, catalogue, facade, read, recheck
from automind.acquisition.api.car import CarData
from automind.acquisition.api.contracts import (
    AcquireRequest,
    AcquireResult,
    Backend,
    CatalogueVariant,
    DatasetVersion,
    Emit,
    LineupRead,
    RecheckResult,
    RevalidateResult,
    StoredLineup,
    Tried,
    VariantDraft,
    VersionsRead,
    WebHint,
)
from automind.acquisition.gold.infrastructure import wiring as gold
from automind.acquisition.identity_readers import web as identity
from automind.acquisition.identity_readers.infrastructure import wiring as identity_wiring
from automind.acquisition.infrastructure.wiring import live_acq_ports


class EngineBackend:
    """Every call of `acquisition.api`, bound to the engine's modules."""

    def live_ports(self) -> Any:
        return live_acq_ports()

    async def acquire(self, req: AcquireRequest, emit: Emit | None, ports: Any) -> AcquireResult:
        return await facade.acquire(req, emit, ports=ports)

    async def missing_critical(self, variant_id: str, powertrain: str | None) -> list[str]:
        return await read.missing_critical(variant_id, powertrain)

    async def last_done(self, variant_ids: list[str]) -> dict[str, dict[str, Any]]:
        return await read.last_done(variant_ids)

    async def ev_counts(self, variant_ids: list[str]) -> dict[str, Any]:
        return await read.ev_counts(variant_ids)

    async def powertrains(self, variant_ids: list[str]) -> dict[str, str | None]:
        return await read.powertrains(variant_ids)

    async def registry_done(self, variant_ids: list[str]) -> dict[str, dict[str, Any]]:
        return await read.registry_done(variant_ids)

    async def unmet_areas(self, variant_ids: list[str]) -> dict[str, set[str]]:
        return await read.unmet_areas(variant_ids)

    async def tried_by_area(self, variant_id: str) -> dict[str, list[Tried]]:
        return await facade.tried_by_area(variant_id)

    async def gearbox_families_mixed(self, variant_id: str) -> bool:
        return await facade.gearbox_families_mixed(variant_id)

    async def reselect(self, variant_id: str) -> None:
        await facade.reselect(variant_id)

    async def recheck_value(self, variant_id: str, attribute: str, rules: dict[str, Any] | None) -> RecheckResult:
        return await recheck.recheck_value(variant_id, attribute, rules=rules)

    async def revalidate_claims(self, rules: dict[str, Any] | None) -> RevalidateResult:
        return await recheck.revalidate_claims(rules)

    async def recheck_minimums(self, variant_id: str) -> None:
        await recheck.recheck_minimums(variant_id)

    async def lineup(self, ports: Any, make: str, official: str | None, max_pages: int,
                     market: str) -> LineupRead | None:  # fmt: skip
        return await identity.lineup(ports, make, official=official, max_pages=max_pages, market=market)

    async def versions(
        self, ports: Any, make: str, model: str, generation: str | None, year: int | None, queries: list[str],
        limits: dict[str, Any], done: set[str] | None, market: str,
    ) -> VersionsRead | None:  # fmt: skip
        return await identity.versions(ports, make, model, generation, year=year, queries=queries, limits=limits,
                                       done=done, market=market)  # fmt: skip

    async def generation_hints(self, ports: Any, query: str, lineup_url: str | None, user_url: str | None,
                               prices: bool, market: str) -> list[WebHint]:  # fmt: skip
        return await identity.generation_hints(ports, query, lineup_url=lineup_url, user_url=user_url, prices=prices,
                                               market=market)  # fmt: skip

    async def dataset_versions(self, ports: Any, make: str, model: str, generation: str | None, fuel: str | None,
                               year_from: int | None) -> list[DatasetVersion]:  # fmt: skip
        found = await identity_wiring.dataset_versions(ports).run(make, model, fuel, year_from)
        url = identity_wiring.source_url()
        return [DatasetVersion(fuel=v.fuel, engine_kw=v.engine_kw, displacement_cc=v.displacement_cc,
                               years_from=v.years_from, years_to=v.years_to, registrations=v.registrations,
                               power_is_max=v.power_is_max, datasets=list(v.datasets), names=list(v.names),
                               source_url=url) for v in found]  # fmt: skip

    async def record_challenge_gold(self, variant_id: str, attribute: str, outcome: str, value: str | float | None,
                                    unit: str | None, challenge_id: str | None) -> bool:  # fmt: skip
        return await gold.challenge_gold().record(variant_id, attribute, outcome, value, challenge_id, unit)

    async def catalogue_models(self, make: str) -> set[str]:
        return await catalogue.catalogue_models(make)

    async def find_variants(self, make: str, model: str) -> list[CatalogueVariant]:
        return await catalogue.find_variants(make, model)

    async def get_variant(self, variant_id: str) -> CatalogueVariant | None:
        return await catalogue.get_variant(variant_id)

    async def upsert_variant(self, draft: VariantDraft) -> CatalogueVariant:
        return await catalogue.upsert_variant(draft)

    async def stale_areas(self, variant_id: str, areas: tuple[str, ...]) -> list[str]:
        return await catalogue.stale_areas(variant_id, areas)

    async def cached_lineup(self, make: str, market: str, ttl_days: int) -> StoredLineup | None:
        return await catalogue.cached_lineup(make, market, ttl_days)

    async def store_lineup(self, lineup: StoredLineup) -> None:
        await catalogue.store_lineup(lineup)

    async def car_data(self, variant_id: str) -> CarData | None:
        return await car_data.car_data(variant_id)

    async def evidence_refs(self, ids: list[str]) -> dict[str, dict[str, str]]:
        return await car_data.evidence_refs(ids)


BACKEND: Backend = EngineBackend()
