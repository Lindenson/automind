"""The blame judge (spec 011 T071, research R9): settles a disputed wrong signal.

Code decides the obvious cases (acquisition/domain/blame.py). A disputed one — the truth is on the raw page but not
in the excerpt, or the truth is a MEDIUM-confidence gold value — is recorded unapplied and queued here. A web-reader
role (no tools; the page only inside <untrusted_document>) answers a closed `{component, quote}`. The answer is
accepted only when the quote occurs in the stored page (`evidence.occurs`) and holds the number the component
implies (the reference value for parser/extractor/units/fusion, the stored value for source); for a reader's claim
the current reader version is re-run on the snapshot and its reading is journalled. Otherwise, or without budget,
the code's vector stands. Either way the signal is then applied (`RegistryRepo.resolve`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel, Field

from automind.acquisition.domain.blame import UNIT_RULES, near, numbers
from automind.acquisition.domain.versions import parse_key
from automind.domain.evidence import occurs

log = logging.getLogger(__name__)
ROLE = "blame_judge"
PROMPT = Path(__file__).resolve().parents[2] / "orchestration" / "prompts" / "blame_judge.md"
EST_EUR = 0.002  # one call of a flash-lite web reader on ≤ 8,000 characters
PAGE_CHARS = 8000
T = TypeVar("T", bound=BaseModel)


class Verdict(BaseModel):
    component: Literal["source", "relevance", "parser", "extractor", "units_sense", "fusion"]
    quote: str = Field(max_length=500)


class LLM(Protocol):
    async def structured(self, role: str, schema: type[T], system: str, user: str) -> T: ...


class GatewayLLM:
    async def structured(self, role: str, schema: type[T], system: str, user: str) -> T:
        from automind.infrastructure import llm_gateway  # noqa: PLC0415

        return await llm_gateway.structured(role, schema, system, user)


def _system() -> str:
    return PROMPT.read_text(encoding="utf-8")


def user_message(attribute: str, ours: float | None, truth: float | None, excerpt: str, url: str, page: str) -> str:
    return (
        f"Attribute: {attribute}\nStored value: {ours}\nReference value: {truth}\nQuoted excerpt: {excerpt}\n\n"
        f'<untrusted_document url="{url}">\n{page[:PAGE_CHARS]}\n</untrusted_document>'
    )


def accept(v: Verdict, page: str, attribute: str, ours: float | None, truth: float | None) -> tuple[bool, str]:
    """Code's check of the judge's answer (never the model's word alone)."""
    if not v.quote.strip() or not occurs(v.quote, page):
        return False, "the quote is not on the stored page"
    nums = numbers(v.quote)
    if v.component == "source":
        ok = ours is not None and any(near(n, ours, ("rel", 0.005)) for n in nums)
        return ok, "" if ok else "the quote does not state the stored value"
    if v.component == "relevance":
        return True, ""
    if truth is None:
        return False, "no reference value to check the quote against"
    readings = [truth, *(truth / f for f in UNIT_RULES.get(attribute, {}).values())]
    ok = any(near(n, r, ("rel", 0.005)) for n in nums for r in readings)
    return ok, "" if ok else "the quote does not hold the reference value"


def rerun_reader(producer_version: str | None, raw: bytes, attribute: str, spec: Any = None) -> dict[str, Any] | None:
    """The claim's reader version (a `ParserSpec`; the YAML v1 reader when none is given) on the stored page: what it
    reads for the attribute."""
    if not producer_version:
        return None
    try:
        rid, _ = parse_key(producer_version)
        from automind.acquisition.infrastructure.fetch import decode_body  # noqa: PLC0415
        from automind.acquisition.parsing import interpreter  # noqa: PLC0415
        from automind.acquisition.parsing.migrate_v1 import yaml_specs  # noqa: PLC0415

        spec = spec or yaml_specs().get(rid)
        if spec is None:
            return None
        reading = interpreter.read(spec, decode_body(raw, None))
    except Exception:  # noqa: BLE001 - a broken page or reader reads as nothing
        return {"reader": producer_version, "rows": 0, "values": []}
    rows = [r for r in (reading.rows if reading else []) if r.attribute == attribute]
    return {"reader": producer_version, "rows": len(rows), "values": [r.raw_value for r in rows][:5]}


async def _stored_spec(producer_version: str | None) -> Any:
    from automind.acquisition.parsing import store  # noqa: PLC0415

    try:
        v = await store.version(producer_version) if producer_version else None
    except Exception:  # noqa: BLE001 - a legacy key or no parser table: the YAML reader
        return None
    return v.spec if v is not None else None


@dataclass
class _Case:
    sig: Any
    claim: Any
    truth: float | None
    url: str
    page: str
    raw: bytes


async def _load(signal_id: str) -> _Case | None:
    from sqlalchemy import select  # noqa: PLC0415

    from automind.acquisition.reputation.signals import page_text_of  # noqa: PLC0415
    from automind.acquisition.snapshots import store  # noqa: PLC0415
    from automind.infrastructure.db import Claim, Document, Evidence, GoldValueRow, TruthSignal, sessionmaker  # noqa: PLC0415

    async with sessionmaker()() as s:
        sig = await s.get(TruthSignal, signal_id)
        if sig is None or not sig.disputed:
            return None
        claim = await s.get(Claim, sig.claim_id) if sig.claim_id else None
        gold = await s.get(GoldValueRow, sig.gold_id) if sig.gold_id else None
        row = None
        if claim is not None:
            q = (
                select(Evidence.url, Document.text)
                .join(Document, Evidence.document_id == Document.id, isouter=True)
                .where(Evidence.id == claim.evidence_id)
            )
            row = (await s.execute(q)).first()
    url, doc_text = (row[0], row[1] or "") if row else ("", "")
    raw = b""
    if sig.snapshot_id:
        try:
            raw, _ = await store.load(sig.snapshot_id)
        except KeyError:
            raw = b""
    truth = gold.value_num if gold is not None else _num((sig.details or {}).get("replaced_by"))
    page = f"{doc_text}\n{page_text_of(raw)}" if raw else doc_text
    return _Case(sig, claim, truth, url, page, raw)


async def judge(signal_id: str, llm: LLM | None = None, charge: Any = None) -> dict[str, Any]:
    """Settle one disputed signal. `charge(eur)` raises when the day's budget is spent."""
    from automind.acquisition.registry.infrastructure.repo import RegistryRepo  # noqa: PLC0415
    from automind.acquisition.worker.budget import BudgetExceeded  # noqa: PLC0415
    from automind.infrastructure.config import load_yaml  # noqa: PLC0415

    case = await _load(signal_id)
    if case is None:
        return {"skipped": "settled"}
    sig, claim, truth, url, page, raw = case.sig, case.claim, case.truth, case.url, case.page, case.raw
    repo = RegistryRepo(load_yaml("registry.yaml"))
    code_vector = dict(sig.blame_vector or {"source": 1.0})
    comps = dict((sig.details or {}).get("components") or {})
    ours = claim.value_num if claim is not None else None
    attribute = sig.attribute or ""
    result: dict[str, Any] = {"signal": signal_id, "code": code_vector}
    if claim is not None and claim.producer == "reader":
        spec = await _stored_spec(claim.producer_version) if raw else None
        result["rerun"] = rerun_reader(claim.producer_version, raw, attribute, spec) if raw else None
    try:
        if charge is not None:
            await charge(EST_EUR)
        v = await (llm or GatewayLLM()).structured(
            ROLE, Verdict, _system(), user_message(attribute, ours, truth, claim.excerpt if claim else "", url, page)
        )
    except BudgetExceeded:
        await repo.resolve(signal_id, code_vector, comps, "judge skipped (budget): code vector")
        return {**result, "verdict": "budget", "applied": code_vector}
    except Exception as e:  # noqa: BLE001 - a failed call leaves the code's decision
        log.warning("blame_judge.call_failed signal=%s: %s", signal_id, e)
        await repo.resolve(signal_id, code_vector, comps, f"judge failed ({type(e).__name__}): code vector")
        return {**result, "verdict": "error", "applied": code_vector}
    ok, why = accept(v, page, attribute, ours, truth)
    if not ok:
        await repo.resolve(signal_id, code_vector, comps, f"judge answer rejected ({why}): code vector")
        return {**result, "verdict": "rejected", "why": why, "answer": v.model_dump(), "applied": code_vector}
    component = v.component
    if component in ("parser", "extractor") and claim is not None:
        component = "parser" if claim.producer == "reader" else "extractor"  # the producer decides which reader
    vector = {component: 1.0}
    pv = claim.producer_version if claim is not None else None
    model = claim.model if claim is not None else None
    keys = {
        "parser": pv or "unknown",
        "extractor": f"{pv or 'unknown'}|{model or 'unknown'}",
        "units_sense": "judge",
        "fusion": "merge@1",
        "relevance": comps.get("relevance") or "page_relevance",
    }
    if component in keys:
        comps = {**comps, component: keys[component]}
    await repo.resolve(signal_id, vector, comps, f"judge: {component}, quote verified on the stored page")
    return {**result, "verdict": "accepted", "answer": v.model_dump(), "applied": vector}


def _num(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
