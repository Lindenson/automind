"""A small stored world for the honest-reputation tests (spec 011 US3): variants, sources, pages, accepted claims,
selected values (by the pure `evidence.select_all`, as merge does) and gold. Writes the tables research writes,
without running research."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select

from automind.acquisition.gold import repo as gold_repo
from automind.acquisition.gold.domain.match import GoldValue
from automind.domain import evidence as ev
from automind.infrastructure import db
from automind.infrastructure.db import models as m

REGISTRY_TABLES = (m.RegistryAttempt, m.RegistryChange, m.TruthSignal, m.CapabilityRow, m.SourceRow,
                   m.ComponentReputation)  # fmt: skip
UNITS = {"max_power": "kW", "max_torque": "N·m", "curb_mass": "kg", "displacement": "cm³", "boot_volume": "L",
         "seats": ""}  # fmt: skip


class World:
    def __init__(self, tag: str) -> None:
        self.tag = tag
        self.variants: list[str] = []
        self.docs: list[str] = []
        self.clock = datetime.now(UTC) - timedelta(days=1)

    def tick(self) -> datetime:
        self.clock += timedelta(seconds=1)
        return self.clock

    async def clear_registry(self) -> None:
        async with db.sessionmaker()() as s:
            for t in REGISTRY_TABLES:
                await s.execute(delete(t))
            await s.execute(delete(m.AcqTask).where(m.AcqTask.kind == "blame_judge"))
            await s.commit()

    async def source(self, domain: str, source_type: str, family: str | None = None, status: str = "candidate",
                     market: str = "ES", area: str = "specs") -> str:  # fmt: skip
        async with db.sessionmaker()() as s:
            if await s.get(m.SourceRow, domain) is None:
                s.add(m.SourceRow(domain=domain, source_type=source_type, family=family or domain, markets=[market],
                                  access="ok"))  # fmt: skip
                await s.flush()
            cap = m.CapabilityRow(domain=domain, area=area, market=market, status=status,
                                  status_since=datetime.now(UTC) - timedelta(days=2))  # fmt: skip
            s.add(cap)
            await s.commit()
            return cap.id

    async def variant(self, name: str, powertrain: str = "ICE", fuel: str = "petrol") -> str:
        async with db.sessionmaker()() as s:
            v = db.Variant(canonical_key=f"rep|{self.tag}|{name}|{db.uid()}", make="RepMake", model=f"Honest {name}",
                           generation=f"G-{self.tag}", variant_name=name, powertrain=powertrain, fuel=fuel)  # fmt: skip
            s.add(v)
            await s.commit()
            self.variants.append(v.id)
            return v.id

    async def gold(self, variant_id: str, values: dict[str, float]) -> None:
        await gold_repo.upsert_dataset(gold_repo.DatasetInfo(gold_repo.REFERENCE_SET, "Reference vehicles",
                                                             "reference_set", "internal"))  # fmt: skip
        rows = []
        for a, x in values.items():
            kind, tol = gold_repo.tolerance_of(a)
            rows.append(GoldValue(variant_id=variant_id, attribute=a, value_num=float(x), unit=UNITS.get(a, ""),
                                  tolerance=tol, tolerance_kind=kind, origin="reference_set",
                                  match_rule="reference_set", confidence="HIGH",
                                  dataset_id=gold_repo.REFERENCE_SET))  # fmt: skip
        await gold_repo.replace(gold_repo.REFERENCE_SET, variant_id, rows)

    async def page(self, variant_id: str, domain: str, source_type: str, text: str,
                   claims: Iterable[tuple[str, float, str]], producer: str = "extractor",
                   producer_version: str | None = "extract_specs@v3", model: str | None = "fake:model",
                   snapshot_id: str | None = None) -> list[str]:  # fmt: skip
        """One page of `domain` about the variant and its accepted claims (attribute, value, excerpt)."""
        url = f"https://{domain}/{self.tag}/{variant_id[:8]}/{db.uid()[:6]}"
        ids = []
        async with db.sessionmaker()() as s:
            doc = db.Document(url=url, title=domain, text=text, url_hash=db.uid().replace("-", "") * 2)
            s.add(doc)
            await s.flush()
            self.docs.append(doc.id)
            e = db.Evidence(variant_id=variant_id, document_id=doc.id, url=url, source_name=domain, domain=domain,
                            source_type=source_type)  # fmt: skip
            s.add(e)
            await s.flush()
            for attr, value, excerpt in claims:
                c = db.Claim(variant_id=variant_id, evidence_id=e.id, attribute=attr, area="specs",
                             raw_value=str(value), raw_unit=UNITS.get(attr), value_num=float(value), excerpt=excerpt,
                             provenance="SOURCED_FACT", status="ACCEPTED",
                             extracted_by="READER" if producer == "reader" else "LLM", producer=producer,
                             producer_version=producer_version, model=model if producer != "reader" else None,
                             snapshot_id=snapshot_id, created_at=self.tick())  # fmt: skip
                s.add(c)
                await s.flush()
                ids.append(c.id)
            await s.commit()
        return ids

    async def select(self, variant_id: str) -> dict[str, Any]:
        """Selected values of the variant from its accepted claims (merge's rule, pure domain)."""
        async with db.sessionmaker()() as s:
            q = (
                select(db.Claim, db.Evidence)
                .join(db.Evidence, db.Claim.evidence_id == db.Evidence.id)
                .where(db.Claim.variant_id == variant_id, db.Claim.status == "ACCEPTED")
            )
            rows = (await s.execute(q)).all()
            claims = [ev.ClaimIn(c.id, c.attribute, c.value_num if c.value_num is not None else (c.value_text or ""),
                                 e.source_type, e.domain, c.scope) for c, e in rows]  # fmt: skip
            sel = {k: v for k, v in ev.select_all(claims).items() if v.available}
            await s.execute(delete(db.SpecValue).where(db.SpecValue.variant_id == variant_id))
            for k, x in sel.items():
                s.add(db.SpecValue(variant_id=variant_id, attribute=k, available=True,
                                   value_num=x.value if isinstance(x.value, float) else None,
                                   value_text=x.value if isinstance(x.value, str) else None, provenance=x.provenance,
                                   confidence=x.confidence, confidence_rule=x.confidence_rule,
                                   resolution_rule=x.resolution_rule, claim_ids=x.claim_ids,
                                   alternatives=x.alternatives))  # fmt: skip
            await s.commit()
        return {k: x.value for k, x in sel.items()}

    async def cap(self, domain: str, area: str = "specs") -> m.CapabilityRow:
        async with db.sessionmaker()() as s:
            q = select(m.CapabilityRow).where(m.CapabilityRow.domain == domain, m.CapabilityRow.area == area)
            return (await s.execute(q)).scalar_one()

    async def signals(self, **where: Any) -> list[m.TruthSignal]:
        async with db.sessionmaker()() as s:
            q = select(m.TruthSignal)
            for k, v in where.items():
                q = q.where(getattr(m.TruthSignal, k) == v)
            return list((await s.execute(q)).scalars())

    async def cleanup(self) -> None:
        async with db.sessionmaker()() as s:
            ids = self.variants
            await s.execute(delete(db.SpecValue).where(db.SpecValue.variant_id.in_(ids)))
            await s.execute(delete(db.Claim).where(db.Claim.variant_id.in_(ids)))
            await s.execute(delete(db.Evidence).where(db.Evidence.variant_id.in_(ids)))
            await s.execute(delete(db.Document).where(db.Document.id.in_(self.docs)))
            await s.execute(delete(db.GoldValueRow).where(db.GoldValueRow.variant_id.in_(ids)))
            await s.execute(delete(db.Variant).where(db.Variant.id.in_(ids)))
            await s.commit()
        await self.clear_registry()
