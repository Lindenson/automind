"""The engine behind `acquisition.api`: one object that implements the api's `Backend` protocol (spec 012 T027).

`acquisition.api` is the only engine module the chat may import, and it imports nothing of the engine. It reaches
the engine through `Backend`, implemented here by delegating to the engine's modules; mypy checks this class
against the protocol, so the facade is typed end to end without `type: ignore`.
"""

from __future__ import annotations

from typing import Any

from automind.acquisition import facade, read, recheck
from automind.acquisition.api.contracts import (
    AcquireRequest,
    AcquireResult,
    Backend,
    DatasetVersion,
    Emit,
    LineupRead,
    RecheckResult,
    RevalidateResult,
    Tried,
    VersionsRead,
    WebHint,
)
from automind.acquisition.gold import repo as gold_repo
from automind.acquisition.gold import versions as gold_versions
from automind.acquisition.infrastructure.wiring import live_acq_ports
from automind.acquisition.pipeline import identity


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
        found = await gold_versions.registered_versions(ports, make, model, generation, fuel, year_from)
        url = gold_versions.source_url()
        return [DatasetVersion(fuel=v.fuel, engine_kw=v.engine_kw, displacement_cc=v.displacement_cc,
                               years_from=v.years_from, years_to=v.years_to, registrations=v.registrations,
                               power_is_max=v.power_is_max, datasets=list(v.datasets), names=list(v.names),
                               source_url=url) for v in found]  # fmt: skip

    async def record_challenge_gold(self, variant_id: str, attribute: str, outcome: str, value: str | float | None,
                                    unit: str | None, challenge_id: str | None) -> bool:  # fmt: skip
        return await gold_repo.record_challenge(variant_id, attribute, outcome, value, challenge_id, unit)


BACKEND: Backend = EngineBackend()
