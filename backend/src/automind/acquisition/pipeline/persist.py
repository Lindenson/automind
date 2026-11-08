"""S6 persist (spec 011 strangler, research R5): what a page gave becomes its evidence row and rows — the checked
spec claims (the validator role for uncertain pages or values that contradict the stored ones), the reader's table
rows, and the items of the other areas (`domain/items.py`), each only with a verbatim excerpt. One page is one
`EvidenceStore.save` (one transaction); the store's `PipelineStoreUnavailable` propagates (the job fails).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel

from automind.acquisition.domain.claims import REJECTED_PREFIX, ClaimStatus
from automind.acquisition.parsing.extraction import areas
from automind.acquisition.parsing.extraction import extract as ex
from automind.acquisition.parsing.extraction.contracts import GENERATION_WIDE
from automind.acquisition.pipeline import stamp
from automind.acquisition.pipeline.domain import items
from automind.acquisition.pipeline.domain.rows import ClaimRow, EvidenceIn, PageRow
from automind.acquisition.pipeline.domain.variant import VariantFacts
from automind.acquisition.pipeline.locate import favourite_priority
from automind.acquisition.pipeline.scope import is_unverified
from automind.acquisition.pipeline.validate import VALIDATOR_REJECTS, ReaderClaim, check, plausibility_ctx, sense_before
from automind.acquisition.ports import AcqPorts
from automind.shared import evidence as ev
from automind.shared.contracts.web import Page, WebDoc
from automind.shared.evidence import sense
from automind.shared.vehicle import specs

VERSION = "persist@1"

Checked = tuple[Any, str, float | None, str | None, str | None]  # (claim, status, number, text, reject rule)


def evidence_in(v: VariantFacts, d: WebDoc, page: Page | None = None, fav: int | None = None) -> EvidenceIn:
    """The page as evidence for the variant (`fav`: the favourite's priority; the stored page's document, if any)."""
    return EvidenceIn(variant_id=v.id, document_id=page.document_id if page is not None else None, url=d.url,
                      title=d.title, text=d.text, source_name=d.title[:200], domain=ev.domain_of(d.url),
                      source_type=ev.classify_source(d.url), snippet_only=d.snippet_only, favourite_priority=fav,
                      unverified=is_unverified(ev.domain_of(d.url)))  # fmt: skip


async def persist_extraction(ports: AcqPorts, v: VariantFacts, area: str, d: WebDoc, out: BaseModel, target: str,
                             uncertain: bool, page: Page | None = None, known: dict[str, float] | None = None,
                             values_rejected: dict[str, int] | None = None, *,
                             car_year: int | None = None) -> tuple[int, int]:  # fmt: skip
    """Store what the extraction role read on a page; returns (accepted, rejected)."""
    evidence = evidence_in(v, d, page, favourite_priority(ports, v, d.url))
    rows: Sequence[PageRow]
    if area in areas.SPEC_AREAS:
        rejected_by = values_rejected if values_rejected is not None else defaultdict(int)
        claims = await _spec_claims(ports, v, area, d, evidence, out, target, uncertain, known or {})
        accepted, rejected = _count(claims, rejected_by)
        rows = claims
    else:
        rates = {k: float(x) for k, x in (ports.ref.feasibility.get("currency_to_eur") or {}).items()}
        k = items.ExcerptCounter(d.text)
        rows = items.area_rows(v, area, d.url, d.title, out, k, rates, car_year)
        accepted, rejected = k.accepted, k.rejected
    await ports.stores.evidence.save(evidence, rows)
    return accepted, rejected


async def persist_reading(ports: AcqPorts, v: VariantFacts, area: str, d: WebDoc, reading: Any,
                          known: dict[str, float], values_rejected: dict[str, int],
                          page: Page | None) -> tuple[int, int]:  # fmt: skip
    """Values read from a favourite site's table without AI (FR-009, FR-010): same provenance and checks (unit
    layer, plausibility); the excerpt is the table row the reader read. Returns (accepted, rejected)."""
    evidence = evidence_in(v, d, page, favourite_priority(ports, v, d.url))
    ctx = plausibility_ctx(v, known)
    rows: list[ClaimRow] = []
    for row in reading.rows:
        if row.attribute not in specs.ATTRS:
            continue
        c, bad = sense_before(ReaderClaim(row.attribute, row.raw_value, row.raw_unit, row.excerpt), v,
                              evidence.source_type, d.url)  # fmt: skip
        status, num, txt, rule = bad or check(c, d, ctx, ports.ref.plausibility, excerpt_checked=True)
        rows.append(_claim(v, area, evidence, c, status, num, txt, rule, "VARIANT", "READER",
                           stamp.reader(reading, page)))  # fmt: skip
    accepted, rejected = _count(rows, values_rejected)
    await ports.stores.evidence.save(evidence, rows)
    return accepted, rejected


async def _spec_claims(ports: AcqPorts, v: VariantFacts, area: str, d: WebDoc, e: EvidenceIn, out: Any, target: str,
                       uncertain: bool, known: dict[str, float]) -> list[ClaimRow]:  # fmt: skip
    """The extraction's claims checked (sense, excerpt, unit, plausibility), then the validator role's verdicts on an
    uncertain page or on values that contradict the stored ones (> 6 %)."""
    ctx = plausibility_ctx(v, known)
    checked: list[Checked] = []
    for c0 in out.claims:
        c, bad = sense_before(c0, v, e.source_type, d.url)
        checked.append((c, *(bad or check(c, d, ctx, ports.ref.plausibility))))
    verdicts = await _validator_verdicts(ports, d, target, checked, uncertain, known)
    market = sense.market_fits(d.url, area)
    rows: list[ClaimRow] = []
    for i, (c, status, num, txt, rule) in enumerate(checked):
        if status == ClaimStatus.ACCEPTED and not market.ok and c.attribute in ("official_price_es",):
            status, rule = ClaimStatus.REJECTED_OTHER_MARKET, market.rule_id
        scope = "GENERATION" if d.snippet_only and c.scope == "VARIANT" else c.scope
        verdict = verdicts.get(i)
        if status == ClaimStatus.ACCEPTED and verdict in VALIDATOR_REJECTS:
            status = f"{REJECTED_PREFIX}{verdict}"
        elif status == ClaimStatus.ACCEPTED and verdict == GENERATION_WIDE:
            scope = "GENERATION"  # kept, but LOW confidence (FR-018)
        rows.append(_claim(v, area, e, c, status, num, txt, rule, scope, "LLM", stamp.extractor(d)))
    return rows


async def _validator_verdicts(ports: AcqPorts, d: WebDoc, target: str, checked: list[Checked], uncertain: bool,
                              known: dict[str, float]) -> dict[int, str]:  # fmt: skip
    conflicting = {
        i for i, (c, st, num, _, _) in enumerate(checked)
        if st == ClaimStatus.ACCEPTED and num is not None and c.attribute in known
        and abs(num - known[c.attribute]) > max(abs(known[c.attribute]) * 0.06, 1e-9)
    }  # fmt: skip
    if not (uncertain or conflicting) or not any(st == ClaimStatus.ACCEPTED for _, st, *_ in checked):
        return {}
    verdicts = await ex.validate_claims(
        ports.llm, ports.ref.prompts["validator"], target, d,
        [{"label": c.attribute, "value": c.raw_value, "excerpt": c.excerpt} for c, *_ in checked],
    )  # fmt: skip
    if not uncertain:  # only the conflicting claims were in question
        verdicts = {i: verdicts[i] for i in conflicting if i in verdicts}
    return verdicts


def _claim(v: VariantFacts, area: str, e: EvidenceIn, c: Any, status: str, num: float | None, txt: str | None,
           rule: str | None, scope: str, by: str, who: dict[str, Any]) -> ClaimRow:  # fmt: skip
    return ClaimRow(variant_id=v.id, attribute=c.attribute, area=area, raw_value=c.raw_value, raw_unit=c.unit,
                    value_num=num, value_text=txt, excerpt=c.excerpt, scope=scope,
                    provenance=ev.assign_provenance(e.source_type, c.attribute), status=status, reject_rule=rule,
                    extracted_by=by, **who)  # fmt: skip


def _count(rows: Sequence[ClaimRow], values_rejected: dict[str, int]) -> tuple[int, int]:
    """(accepted, rejected) claims; each rejection counted by its reason."""
    accepted = rejected = 0
    for row in rows:
        if row.status == ClaimStatus.ACCEPTED:
            accepted += 1
        else:
            rejected += 1
            values_rejected[row.status.removeprefix(REJECTED_PREFIX).lower()] += 1
    return accepted, rejected
