"""Strategy sourced_versions (spec 008 US6): the car narrowed over the versions of its generation that sources list
(the versions store, else a search). A new car is one of the versions on sale now (the facelift's, not the first
years', chat 5821ac77); a used one, of the versions sold in its year (FR-023). The settled version is stored in
the catalogue (one row per real version, FR-019). Gives up (None) when no source lists the versions."""

from __future__ import annotations

import re

from automind.acquisition.api import CatalogueVariant
from automind.chat.application.ports import Ports
from automind.chat.application.services.identification import versions
from automind.chat.application.services.identification.catalogue import upsert_variant
from automind.chat.application.services.identification.contracts import Placed, VariantIdentity
from automind.chat.application.services.identification.stages.narrow_ladder import (
    asked,
    decide,
    generation_of,
    others,
    reconcile,
)
from automind.chat.application.services.identification.stages.settle import proposed, settle
from automind.chat.domain.case import CaseCar, IdentifyOutcome, LadderMemo
from automind.chat.domain.identification import ladder

_AWD_WORD = re.compile(r"awd|4motion|quattro|xdrive|4x4|4wd", re.IGNORECASE)  # "2.0 TDI 4Motion" already says AWD


class SourcedVersions:
    """The first fallback: the versions the sources list for the model's generation (spec 008 FR-020)."""

    def __init__(self, ports: Ports) -> None:
        self.ports = ports

    async def identify(self, placed: Placed) -> IdentifyOutcome | None:
        """The ladder over the sourced versions; None when no versions store or no sourced list."""
        ports, case, car, year = self.ports, placed.case, placed.car, placed.year
        if not (car.make and car.model) or ports.versions is None:
            return None
        events = reconcile(ports, car)
        new = car.condition != "USED"
        gen = generation_of(ports, car, year)
        try:
            fuel = car.constraints.engine_hint.fuel if car.constraints.engine_hint else None
            g = await versions.lookup(ports, car.make, car.model, generation=gen, year=None if new else car.year,
                                      new=new, current_year=year, fuel=fuel, market=car.market)  # fmt: skip
        except Exception:  # noqa: BLE001 - a failed look-up never blocks the intake: the fallback identifies
            g = None
        if g is None or not g.versions:
            return None
        memo = car.ladder or LadderMemo()
        memo.certainty, memo.generation = "SOURCED", g.generation
        memo.generation_from, memo.generation_to = g.years_from, g.years_to
        car.ladder = memo
        pool = ladder.on_sale(g.versions, year) if new else g.versions
        d = decide(ports, case, car, pool, memo, events)
        if not (d.done and d.step.version is not None):
            return asked(car, d, events)
        v = await self._store(car, g, d.step)
        car.variant_id, car.label, car.resolution = v.id, v.label, proposed(car)
        memo.source_url = d.step.version.source_url or None
        memo.source_name = versions.DATASET_SOURCE if any(s.get("dataset") for s in g.sources) else None
        memo.others = others(pool, car.year if not new else None, d.step.version)
        if d.missing and not d.auto:  # the user named something this generation has not: said, the one there is
            events.append({"kind": "ladder_missing", "missing": ", ".join(d.missing), "label": v.label})
        return settle(car, IdentifyOutcome(outcome="IDENTIFIED", missing=d.missing, events=events))

    async def _store(self, car: CaseCar, g: ladder.Generation, step: ladder.Step) -> CatalogueVariant:
        """The catalogue row of the settled version (an existing one is reused, FR-019)."""
        v = step.version
        assert v is not None
        name = v.engine + (f" {ladder.GEARBOX_LABEL.get(step.gearbox, step.gearbox)}" if step.gearbox else "")
        name += " AWD" if step.drive == "AWD" and not _AWD_WORD.search(name) else ""
        ident = VariantIdentity.model_validate({  # the sources' strings, validated as the identity's closed sets
            "make": car.make or g.make, "model": car.model or g.model, "generation": g.generation,
            "generation_years_from": g.years_from, "generation_years_to": g.years_to, "variant_name": name,
            "powertrain": ladder.POWERTRAIN.get(v.fuel or "", "ICE"), "body_class": g.body_class,
            "transmission": step.gearbox, "drive": step.drive, "engine_cc": v.engine_cc, "power_kw": v.power_kw,
            "fuel": v.fuel, "certainty": "exact",
        })  # fmt: skip
        return await upsert_variant(ident, self.ports.ref)
