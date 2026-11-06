"""The car read model (spec 012 T028, research R13): what the engine has stored about one catalogued version, read
in one session — the queries moved from the chat's `compose.load_car` / `tco_car` / `evidence_refs` unchanged —
and handed out as `acquisition.api.car` rows."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlalchemy import select

from automind.acquisition.api.car import (
    CarData,
    ClaimRow,
    EvidenceRow,
    IssueRow,
    MaintenanceRow,
    ManufacturerFactRow,
    RejectedPage,
    ReliabilityStatRow,
    ResearchRunRow,
    RetentionRow,
    ReviewRow,
    SpecValueRow,
    UsedPriceRow,
)
from automind.acquisition.catalogue import view_of
from automind.shared.infrastructure import db

REJECTED_PAGES = 20  # newest rejected pages shown with the sources
_REJECTED = ("OTHER_VARIANT", "NOT_ABOUT_CAR")


async def car_data(variant_id: str) -> CarData | None:
    """Everything stored about one version; None for an unknown one."""
    async with db.sessionmaker()() as s:
        v = await s.get(db.Variant, variant_id)
        if v is None:
            return None
        rows = {name: list((await s.execute(q)).scalars()) for name, q in _rows_of(variant_id, v.make).items()}
        pairs = {name: list((await s.execute(q)).all()) for name, q in _pairs_of(variant_id).items()}
    return CarData(
        variant=view_of(v),
        values={sv.attribute: _row(SpecValueRow, sv) for sv in rows["values"]},
        claims=[(_row(ClaimRow, c), _row(EvidenceRow, e)) for c, e in pairs["claims"]],
        runs=[_row(ResearchRunRow, r) for r in rows["runs"]],
        issues=[(_row(IssueRow, i), _row(EvidenceRow, e)) for i, e in pairs["issues"]],
        used_issues=[_row(IssueRow, i) for i in rows["used_issues"]],
        reviews=[(_row(ReviewRow, r), _row(EvidenceRow, e)) for r, e in pairs["reviews"]],
        stats=[_row(ReliabilityStatRow, x) for x in rows["stats"]],
        manufacturer_facts=[_row(ManufacturerFactRow, f) for f in rows["facts"]],
        retention=[
            (_row(RetentionRow, r), _row(EvidenceRow, e) if e is not None else None) for r, e in pairs["retention"]
        ],  # fmt: skip
        used_prices=[
            UsedPriceRow.model_validate({**_fields(UsedPriceRow, r, but="url"), "url": url})
            for r, url in pairs["used_prices"]
        ],  # fmt: skip
        maintenance=[_row(MaintenanceRow, m) for m in rows["maintenance"]],
        rejected_pages=[
            RejectedPage(
                title=d.title,
                url=d.url,
                final_url=d.final_url,
                fetched_at=d.fetched_at,
                retrieved_at=d.retrieved_at,
                reason=r.reason,
                other=r.other,
            )
            for r, d in pairs["rejected"]
        ],  # fmt: skip
    )


async def evidence_refs(ids: list[str]) -> dict[str, dict[str, str]]:
    """Evidence id -> its source as the report cites it (name, url, type, retrieved_at)."""
    if not ids:
        return {}
    async with db.sessionmaker()() as s:
        rows = (await s.execute(select(db.Evidence).where(db.Evidence.id.in_(ids)))).scalars()
        return {
            e.id: {
                "name": e.source_name,
                "url": e.url,
                "type": e.source_type,
                "retrieved_at": e.retrieved_at.isoformat(),
            }
            for e in rows
        }


def _rows_of(variant_id: str, make: str) -> dict[str, Any]:
    """The queries of one kind of stored row each."""
    return {
        "values": select(db.SpecValue).where(db.SpecValue.variant_id == variant_id),
        "runs": select(db.ResearchRun).where(db.ResearchRun.variant_id == variant_id),
        "stats": select(db.ReliabilityStat).where(db.ReliabilityStat.variant_id == variant_id),
        "facts": select(db.ManufacturerFact).where(db.ManufacturerFact.make == make),
        "maintenance": select(db.MaintenanceItem).where(db.MaintenanceItem.variant_id == variant_id),
        "used_issues": select(db.Issue).where(db.Issue.variant_id == variant_id, db.Issue.area == "used_issues"),
    }


def _pairs_of(variant_id: str) -> dict[str, Any]:
    """The queries of a stored row with its evidence (or document) each."""
    return {
        "claims": select(db.Claim, db.Evidence).join(db.Evidence, db.Claim.evidence_id == db.Evidence.id)
        .where(db.Claim.variant_id == variant_id, db.Claim.status == "ACCEPTED"),
        "issues": select(db.Issue, db.Evidence).join(db.Evidence, db.Issue.evidence_id == db.Evidence.id)
        .where(db.Issue.variant_id == variant_id),
        "reviews": select(db.ReviewItem, db.Evidence).join(db.Evidence, db.ReviewItem.evidence_id == db.Evidence.id)
        .where(db.ReviewItem.variant_id == variant_id),
        "retention": select(db.ValueRetention, db.Evidence)
        .join(db.Evidence, db.ValueRetention.evidence_id == db.Evidence.id, isouter=True)
        .where(db.ValueRetention.variant_id == variant_id),
        "used_prices": select(db.UsedPriceRange, db.Evidence.url)
        .join(db.Evidence, db.UsedPriceRange.evidence_id == db.Evidence.id)
        .where(db.UsedPriceRange.variant_id == variant_id, db.UsedPriceRange.status == "ACCEPTED"),
        "rejected": select(db.PageRelevance, db.Document)
        .join(db.Document, db.PageRelevance.document_id == db.Document.id)
        .where(db.PageRelevance.variant_id == variant_id, db.PageRelevance.verdict.in_(_REJECTED))
        .order_by(db.PageRelevance.created_at.desc())
        .limit(REJECTED_PAGES),
    }  # fmt: skip


def _row[M: BaseModel](model: type[M], orm: Any) -> M:
    """A stored row as its read-model row: the model's fields, read by name."""
    return model.model_validate(_fields(model, orm))


def _fields(model: type[BaseModel], orm: Any, but: str = "") -> dict[str, Any]:
    return {k: getattr(orm, k) for k in model.model_fields if k != but}
