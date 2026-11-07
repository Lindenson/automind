"""Strategy catalogue_rows (spec 008 FR-020): no sourced list of versions — the catalogue rows of the model follow
the same ladder levels: where they differ at a level the person did not state, it is asked; a row is never taken
by being first. The identity is marked less certain. A new car never takes a row a newer row supersedes, and when
only old rows are left its version is asked with the registered versions (chat 5821ac77). Gives up (None) to the
open world when the catalogue has no row, or none of the version the person picked or named."""

from __future__ import annotations

from dataclasses import dataclass

from automind.chat.application.ports import Ports
from automind.chat.application.services.identification.assessment import assess_car
from automind.chat.application.services.identification.contracts import IntakeConfig, Placed, VariantRow
from automind.chat.application.services.identification.stages.ask_stale_version import (
    ask_stale_version,
    newer_versions,
    picked_since,
    registered,
    registered_choice,
)
from automind.chat.application.services.identification.stages.narrow_ladder import (
    Events,
    asked,
    decide,
    reconcile,
)
from automind.chat.application.services.identification.stages.settle import SETTLED, proposed, settle
from automind.chat.domain.case import CaseCar, Choice, IdentifyOutcome, LadderMemo
from automind.chat.domain.identification import ladder
from automind.chat.domain.identification.variant_match import bought_now

MAX_CHOICES = 4  # other rows shown on the card


class CatalogueRows:
    """The second fallback: the catalogue rows of the model, asked level by level like sourced versions."""

    def __init__(self, ports: Ports) -> None:
        self.ports = ports

    async def identify(self, placed: Placed) -> IdentifyOutcome | None:
        """A row the words pick or the ladder settles (marked less certain), the open level asked, or None for the
        open world (no row; only rows older than a registered version the person picked; an old-row case)."""
        ports, case, car, year = self.ports, placed.case, placed.car, placed.year
        memo = _less_certain(car)
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
        # the sources were searched for the versions on sale and listed none (the versions store is there, the
        # ladder fell back), and every row left was first sold long ago: the version may be a pre-facelift one
        years = IntakeConfig.of(ports.ref).catalog_stale_years
        old = now and ports.versions is not None and all(ladder.stale(v, year, years) for v in pool)
        if old and (v := await self._old_rows(placed, d, pool, events)).final:
            return v.outcome
        return _take(car, memo, rows[pool.index(d.step.version)], cands, len(pool), d, events, old)

    async def _old_rows(self, placed: Placed, d: ladder.Decision, pool: list[ladder.Version],
                        events: Events) -> _Verdict:  # fmt: skip
        """Only old rows of a new car: a power they lack goes to the resolver; otherwise the version is asked once
        with the registered versions, and "choose for me" takes the newest registered one (via the resolver)."""
        ports, case, car, year = self.ports, placed.case, placed.car, placed.year
        stated = car.constraints.engine_hint is not None and bool(car.constraints.engine_hint.power_kw)
        if stated and any(m.endswith(" CV") for m in d.missing):  # a power the old rows lack: the resolver
            return _Verdict(final=True)
        if not (stated or d.auto or case.intake.attempt(car.key, "POWER") > 0 or car.chosen_for_me):
            found = await registered(ports, car, pool, year)
            assert d.step.version is not None  # decided above
            return _Verdict(final=True, outcome=ask_stale_version(car, d.step.version, events, found, pool))
        if car.chosen_for_me and not stated:  # "choose for me" on a new car: the version on sale now
            newest = newer_versions(await registered(ports, car, pool, year), pool)
            if newest:
                car.constraints.version_hint = registered_choice(car, newest[0]).engine
                return _Verdict(final=True)
        return _TAKE_ROW


def catalog_version(c: VariantRow) -> ladder.Version:
    """A catalog row as a ladder version (unsourced: the fallback, FR-020)."""
    gearbox, drive = c.get("transmission"), c.get("drive")
    return ladder.Version(engine=str(c.get("variant_name") or c.get("label") or ""), fuel=c.get("fuel"),
                          engine_cc=c.get("engine_cc"), power_kw=c.get("power_kw"),
                          gearboxes=(gearbox,) if gearbox else (), drives=(drive,) if drive else (),
                          years_from=c.get("generation_years_from"), years_to=c.get("generation_years_to"))  # fmt: skip


def current_rows(rows: list[VariantRow], year: int) -> list[VariantRow]:
    """A new car bought now: never a row that ended, or that a newer row of the same engine supersedes (the 2020
    265 CV Sorento PHEV row next to the 2024 facelift's 288 CV row, chat 5821ac77)."""
    vs = [catalog_version(c) for c in rows]
    now = ladder.on_sale(vs, year)
    return [c for c, v in zip(rows, vs, strict=True) if v in now]


def base_first(rows: list[VariantRow]) -> list[VariantRow]:
    """Catalog rows the words do not tell apart, in the base version order (the least power first, then the label):
    the database returns them in any order, and "choose for me" or the ask limit takes the first (FR-009; a
    test database where the 150 CV row came back first took it)."""
    return sorted(rows, key=lambda c: (c.get("power_kw") is None, c.get("power_kw") or 0, c.get("engine_cc") or 0,
                                       str(c.get("label") or "")))  # fmt: skip


@dataclass(frozen=True)
class _Verdict:
    """What the check of old rows decided: `final` ends the strategy with `outcome` (None: the resolver's turn);
    otherwise the row is taken."""

    final: bool
    outcome: IdentifyOutcome | None = None


_TAKE_ROW = _Verdict(final=False)


def _less_certain(car: CaseCar) -> LadderMemo:
    memo = car.ladder or LadderMemo()
    memo.certainty, memo.source_url, memo.others = "LESS_CERTAIN", None, []
    car.ladder = memo
    return memo


def _take(car: CaseCar, memo: LadderMemo, row: VariantRow, cands: list[VariantRow], versions: int,
          d: ladder.Decision, events: Events, old: bool) -> IdentifyOutcome:  # fmt: skip
    """The row is the car's version: taken when it is the only one of a new car, else proposed; the other rows are
    the card's choices."""
    events.append({"kind": "identity_less_certain"})
    fresh = car.resolution not in SETTLED
    car.variant_id, car.label = row["id"], row["label"]
    single = fresh and car.condition != "USED" and versions == 1 and not old
    car.resolution = "AUTO_OK" if single else proposed(car)
    memo.others = [c["label"] for c in cands if c["id"] != row["id"]][:MAX_CHOICES]
    choices = [Choice(label=c["label"], make=c["make"], model=c["model"], variant_id=c["id"])
               for c in cands[:MAX_CHOICES]]  # fmt: skip
    return settle(car, IdentifyOutcome(outcome="IDENTIFIED", choices=choices, missing=d.missing, events=events))
