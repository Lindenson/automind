"""Strategy catalogue_rows (spec 008 FR-020): no sourced list of versions — the catalogue rows of the model follow
the same ladder levels: where they differ at a level the person did not state, it is asked; a row is never taken
by being first. The identity is marked less certain. A new car never takes a row a newer row supersedes, and when
only old rows are left its version is asked with the registered versions (chat 5821ac77). Gives up (None) to the
open world when the catalogue has no row, or none of the version the person picked or named."""

from __future__ import annotations

from typing import Any

from automind.chat.application.ports import Ports
from automind.chat.application.services.identification.assessment import assess_car
from automind.chat.application.services.identification.contracts import Placed
from automind.chat.application.services.identification.stages.ask_stale_version import (
    ask_stale_version,
    newer_versions,
    picked_since,
    registered,
    registered_choice,
)
from automind.chat.application.services.identification.stages.narrow_ladder import (
    asked,
    decide,
    intake_cfg,
    reconcile,
)
from automind.chat.application.services.identification.stages.settle import SETTLED, proposed, settle
from automind.chat.domain.case import Choice, IdentifyOutcome, LadderMemo
from automind.chat.domain.identification import ladder
from automind.chat.domain.identification.variant_match import bought_now

CATALOG_STALE_YEARS = 4  # default; config/search.yaml intake.catalog_stale_years
MAX_CHOICES = 4  # other rows shown on the card


class CatalogueRows:
    def __init__(self, ports: Ports) -> None:
        self.ports = ports

    async def identify(self, placed: Placed) -> IdentifyOutcome | None:  # noqa: PLR0911 - one return per way out
        ports, case, car, year = self.ports, placed.case, placed.car, placed.year
        memo = car.ladder or LadderMemo()
        memo.certainty, memo.source_url, memo.others = "LESS_CERTAIN", None, []
        car.ladder = memo
        events = reconcile(ports, car)
        a = await assess_car(car, ports.ref, year, case.compare_level)
        now = bought_now(car, year)
        cands = current_rows(a.candidates, year) if now else a.candidates
        since = picked_since(car)
        if not cands or (now and since is not None and all((c.get("generation_years_from") or 0) < since
                                                            for c in cands)):  # fmt: skip
            return None  # none, or the person picked a registered version newer than every row (the facelift)
        # the words already pick one row (the ranker): that row; rows the words do not tell apart ("2.0 diesel"
        # with 115 and 150 CV rows) are asked level by level, never taken by being first
        rows = base_first(cands) if a.state.ambiguous and len(cands) > 1 else cands[:1]
        pool = [catalog_version(c) for c in rows]
        d = decide(ports, case, car, pool, memo, events)
        if not d.done or d.step.version is None:
            events.append({"kind": "identity_less_certain"})
            return asked(car, d, events)
        years = int(intake_cfg(ports).get("catalog_stale_years", CATALOG_STALE_YEARS))
        # the sources were searched for the versions on sale and listed none (the versions store is there, the ladder
        # fell back), and every row left was first sold long ago: the version may be a pre-facelift one
        searched = getattr(ports, "versions", None) is not None
        old = now and searched and all(ladder.stale(v, year, years) for v in pool)
        if old:
            stated = car.constraints.engine_hint is not None and bool(car.constraints.engine_hint.power_kw)
            if stated and any(m.endswith(" CV") for m in d.missing):  # a power the old rows lack: the resolver
                return None
            if not (stated or d.auto or case.intake.attempt(car.key, "POWER") > 0 or car.chosen_for_me):
                found = await registered(ports, car, pool, year)
                return ask_stale_version(car, d.step.version, events, found, pool)
            if car.chosen_for_me and not stated:  # "choose for me" on a new car: the version on sale now
                newest = newer_versions(await registered(ports, car, pool, year), pool)
                if newest:
                    car.constraints.version_hint = registered_choice(car, newest[0]).engine
                    return None
        events.append({"kind": "identity_less_certain"})
        row = rows[pool.index(d.step.version)]
        fresh = car.resolution not in SETTLED
        car.variant_id, car.label = row["id"], row["label"]
        single = fresh and car.condition != "USED" and len(pool) == 1 and not old
        car.resolution = "AUTO_OK" if single else proposed(car)
        memo.others = [c["label"] for c in cands if c["id"] != row["id"]][:MAX_CHOICES]
        choices = [Choice(label=c["label"], make=c["make"], model=c["model"], variant_id=c["id"])
                   for c in cands[:MAX_CHOICES]]  # fmt: skip
        return settle(car, IdentifyOutcome(outcome="IDENTIFIED", choices=choices, missing=d.missing, events=events))


def catalog_version(c: dict[str, Any]) -> ladder.Version:
    """A catalog row as a ladder version (unsourced: the fallback, FR-020)."""
    return ladder.Version(engine=str(c.get("variant_name") or c.get("label") or ""), fuel=c.get("fuel"),
                          engine_cc=c.get("engine_cc"), power_kw=c.get("power_kw"),
                          gearboxes=(c["transmission"],) if c.get("transmission") else (),
                          drives=(c["drive"],) if c.get("drive") else (),
                          years_from=c.get("generation_years_from"), years_to=c.get("generation_years_to"))  # fmt: skip


def current_rows(rows: list[dict[str, Any]], year: int) -> list[dict[str, Any]]:
    """A new car bought now: never a row that ended, or that a newer row of the same engine supersedes (the 2020
    265 CV Sorento PHEV row next to the 2024 facelift's 288 CV row, chat 5821ac77)."""
    vs = [catalog_version(c) for c in rows]
    now = ladder.on_sale(vs, year)
    return [c for c, v in zip(rows, vs, strict=True) if v in now]


def base_first(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Catalog rows the words do not tell apart, in the base version order (the least power first, then the label):
    the database returns them in any order, and "choose for me" or the ask limit takes the first (FR-009; a
    test database where the 150 CV row came back first took it)."""
    return sorted(rows, key=lambda c: (c.get("power_kw") is None, c.get("power_kw") or 0, c.get("engine_cc") or 0,
                                       str(c.get("label") or "")))  # fmt: skip
