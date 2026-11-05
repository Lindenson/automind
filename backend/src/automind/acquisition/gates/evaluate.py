"""Old and new versions of a change on the same stored pages (spec 011 US5): the measurement the replay gate, the
shadow gate and the watch share. One code path with live (research R4): readers are the fixed interpreter, values pass
the live checks (`replay/run.read_page`), extractors go through the extraction cache.

Per object kind:
- parser: the old and new specs (offline, socket guard on);
- rule: every running reader with the rules before and after (plausibility paths; other rule paths have no offline
  measure yet: `None`, the gate waits for evidence);
- prompt / role_model: the extractor with the old and new prompt text or model (model calls within the agent's
  budget, cached in `extraction_cache`).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select

from automind.acquisition.domain import gates
from automind.acquisition.domain import replay as scoring
from automind.acquisition.domain.versions import parse_key
from automind.acquisition.parsing.spec import ParserSpec
from automind.acquisition.snapshots.store import SnapshotRef
from automind.infrastructure import config, overrides
from automind.infrastructure.db import AcqChange, PageSnapshot, ParserVersion, PromptVersion, Variant, sessionmaker

EST_EXTRACT_EUR = 0.002  # one extractor call on one page (flash-lite web reader)
Charge = Callable[[float], Awaitable[None]]


@dataclass
class Pair:
    old: list[scoring.PageResult]
    new: list[scoring.PageResult]


class NoMeasure(Exception):  # noqa: N818 - a state, not an error
    """This change has no offline measure (yet)."""


async def refs(ids: list[str]) -> list[SnapshotRef]:
    if not ids:
        return []
    async with sessionmaker()() as s:
        rows = (
            await s.execute(select(PageSnapshot).where(PageSnapshot.id.in_(ids), PageSnapshot.blob_sha256.is_not(None)))
        ).scalars()
        out = [SnapshotRef(r.id, r.url, r.final_url, r.domain, r.fetched_at, r.content_type,
                           tuple(r.variant_ids or ()), str(r.blob_sha256)) for r in rows]  # fmt: skip
    return sorted(out, key=lambda r: (r.fetched_at, r.id))


async def corpus_refs(domains: list[str] | None, since: datetime, until: datetime, limit: int = 5000) -> list[Any]:
    from automind.acquisition.snapshots import store  # noqa: PLC0415

    out: list[SnapshotRef] = []
    async for batch in store.iter_replayable(domains, since, until):
        out += batch
        if len(out) >= limit:
            return out[:limit]
    return out


async def spec_of(key: str | None) -> ParserSpec | None:
    if not key:
        return None
    async with sessionmaker()() as s:
        row = await s.get(ParserVersion, key)
    return ParserSpec.model_validate(row.spec) if row is not None else None


def domains_of(change: AcqChange, old: ParserSpec | None, new: ParserSpec | None) -> list[str]:
    return sorted({d for sp in (old, new) if sp is not None for d in sp.domains})


async def _bodies_variants(rs: list[SnapshotRef]) -> tuple[dict[str, bytes], dict[str, Variant]]:
    from automind.acquisition.replay import run  # noqa: PLC0415
    from automind.acquisition.snapshots import store  # noqa: PLC0415

    bodies = await store.load_bodies(sorted({r.blob_sha256 for r in rs}))
    variants: dict[str, Variant] = {}
    await run._variants({v for r in rs for v in r.variant_ids}, variants)
    return bodies, variants


def _read(rs: list[SnapshotRef], bodies: dict[str, bytes], variants: dict[str, Variant], spec: ParserSpec | None,
          rules: dict[str, Any]) -> list[scoring.PageResult]:  # fmt: skip
    from automind.acquisition.replay.offline import no_network  # noqa: PLC0415
    from automind.acquisition.replay.run import read_page  # noqa: PLC0415

    out = []
    with no_network():
        for r in rs:
            if r.blob_sha256 not in bodies:
                continue
            if spec is None:
                out.append(scoring.PageResult(r.id, r.final_url or r.url, r.variant_ids, 0, []))
            else:
                out.append(read_page(r, bodies[r.blob_sha256], spec, variants, rules))
    return out


async def _parser_pair(c: AcqChange, rs: list[SnapshotRef], **_: Any) -> Pair:
    old, new = await spec_of(c.from_version), await spec_of(c.to_version)
    bodies, variants = await _bodies_variants(rs)
    rules = config.plausibility_rules()
    return Pair(_read(rs, bodies, variants, old, rules), _read(rs, bodies, variants, new, rules))


async def _running_specs() -> list[ParserSpec]:
    from automind.acquisition.parsing import store  # noqa: PLC0415

    return [v.spec for v in await store.running()]


def _spec_for(specs: list[ParserSpec], domain: str) -> ParserSpec | None:
    return next((sp for sp in specs if any(domain == d or domain.endswith("." + d) for d in sp.domains)), None)


def rule_sets(c: AcqChange) -> tuple[dict[str, Any], dict[str, Any]]:
    """(plausibility rules before, after) of a plausibility rule change."""
    if not c.object_key.startswith("plausibility."):
        raise NoMeasure(f"no offline measure for {c.object_key}")
    path = c.object_key.removeprefix("plausibility.")
    current = config.plausibility_rules()
    value = (c.diff or {}).get("to")
    before = (c.diff or {}).get("from")
    after = overrides.set_path(current, path, value)
    if c.status in ("watch", "kept") and before is not None:
        current = overrides.set_path(current, path, before)  # the change is live: "before" is its old value
    return current, after


async def _rule_pair(c: AcqChange, rs: list[SnapshotRef], **_: Any) -> Pair:
    before, after = rule_sets(c)
    specs = await _running_specs()
    bodies, variants = await _bodies_variants(rs)
    old: list[scoring.PageResult] = []
    new: list[scoring.PageResult] = []
    for r in rs:
        sp = _spec_for(specs, r.domain)
        if sp is None:
            continue
        old += _read([r], bodies, variants, sp, before)
        new += _read([r], bodies, variants, sp, after)
    return Pair(old, new)


async def _prompt_texts(c: AcqChange) -> tuple[str, str, str]:
    """(prompt name, old text, new text) of a prompt change; for a model change the active extraction prompt."""
    async with sessionmaker()() as s:
        old = await s.get(PromptVersion, c.from_version) if c.from_version else None
        new = await s.get(PromptVersion, c.to_version)
    if old is None or new is None:
        raise NoMeasure(f"prompt versions of {c.object_key} not found")
    return c.object_key, old.text, new.text


async def _extractor_pair(c: AcqChange, rs: list[SnapshotRef], *, llm: Any = None, charge: Charge | None = None,
                          **_: Any) -> Pair:  # fmt: skip
    from automind.acquisition.infrastructure.fetch import decode_body  # noqa: PLC0415
    from automind.acquisition.infrastructure.pages import main_content  # noqa: PLC0415
    from automind.acquisition.pipeline import extract as extraction  # noqa: PLC0415
    from automind.acquisition.pipeline import job as pipeline_job  # noqa: PLC0415
    from automind.acquisition.replay import run  # noqa: PLC0415
    from automind.application.ports import WebDoc  # noqa: PLC0415
    from automind.infrastructure import llm_gateway  # noqa: PLC0415

    if c.object_kind == "prompt":
        name, old_text, new_text = await _prompt_texts(c)
        models = (None, None)
    else:
        name = "extract_specs"
        async with sessionmaker()() as s:
            act = (
                await s.execute(
                    select(PromptVersion).where(PromptVersion.name == name, PromptVersion.status == "active")
                )
            ).scalar_one()
        old_text = new_text = act.text
        models = (str(c.from_version), str(c.to_version))
    area = next((a for a, p in extraction.PROMPT_FOR_AREA.items() if p == name), None)
    if area is None:
        raise NoMeasure(f"{name} is not an extraction prompt")
    bodies, variants = await _bodies_variants(rs)
    rules = config.plausibility_rules()
    out = Pair([], [])
    for r in rs:
        if r.blob_sha256 not in bodies:
            continue
        url = r.final_url or r.url
        title, body = main_content(decode_body(bodies[r.blob_sha256], None), url)
        d = WebDoc(url, title, body, False, snapshot_id=r.id)
        v = variants.get(r.variant_ids[0]) if r.variant_ids else None
        target = pipeline_job.target_of(v) if v is not None else "the vehicle on this page"
        for text, model, into in ((old_text, models[0], out.old), (new_text, models[1], out.new)):
            if charge is not None:
                await charge(EST_EXTRACT_EUR)
            token = llm_gateway.FORCED_MODELS.set({"extractor": model} if model else None)
            try:
                got = await run._extract_cached(d, r.blob_sha256, name, text, area,
                                                llm_gateway.model_name("extractor"), target, llm=llm)  # fmt: skip
            finally:
                llm_gateway.FORCED_MODELS.reset(token)
            claims = list(getattr(got, "claims", []))
            into.append(scoring.PageResult(r.id, url, r.variant_ids, len(claims),
                                           run._values(r, claims, variants, d, rules, False)))  # fmt: skip
    return out


PAIRS: dict[str, Callable[..., Awaitable[Pair]]] = {
    "parser": _parser_pair, "rule": _rule_pair, "prompt": _extractor_pair, "role_model": _extractor_pair,
}  # fmt: skip


async def pair(c: AcqChange, rs: list[SnapshotRef], *, llm: Any = None, charge: Charge | None = None) -> Pair:
    fn = PAIRS.get(c.object_kind)
    if fn is None:
        raise NoMeasure(f"no offline measure for {c.object_kind} changes")
    return await fn(c, rs, llm=llm, charge=charge)


async def gold_for(pages: list[scoring.PageResult]) -> dict[tuple[str, str], scoring.Gold]:
    from automind.acquisition.replay import run  # noqa: PLC0415

    return await run._gold({v for p in pages for v in p.variant_ids})


def metrics(pages: list[scoring.PageResult], gold: dict[tuple[str, str], scoring.Gold], *,
            yield_pages: list[scoring.PageResult] | None = None) -> gates.Metrics:  # fmt: skip
    """Headline metrics; yield and pass rate from `yield_pages` when given (pages after a redesign), accuracy from
    every gold-covered page."""
    rep = scoring.report("x", pages, gold, config.gold_tolerances())
    if yield_pages is not None:
        y = scoring.report("x", yield_pages, gold, config.gold_tolerances())
        rep.update({k: y[k] for k in ("pages", "yield", "pass_rate", "rows_read", "rows_accepted")})
    found: dict[str, set[str]] = {}
    for p in yield_pages if yield_pages is not None else pages:
        for v in p.values:
            found.setdefault(v.variant_id, set()).add(v.attribute)
    rep["coverage"] = (sum(len(a) for a in found.values()) / len(found)) if found else None
    return gates.Metrics.from_report(rep)


async def measure(c: AcqChange, rs: list[SnapshotRef], *, since: datetime | None = None, llm: Any = None,
                  charge: Charge | None = None) -> tuple[gates.Metrics, gates.Metrics]:  # fmt: skip
    """(old, new) metrics of a change on these stored pages; yield over the pages fetched `since` when given."""
    got = await pair(c, rs, llm=llm, charge=charge)
    gold = await gold_for(got.old + got.new)
    late = {r.id for r in rs if since is None or r.fetched_at >= since}

    def m(pages: list[scoring.PageResult]) -> gates.Metrics:
        sub = [p for p in pages if p.snapshot_id in late] if since is not None else None
        return metrics(pages, gold, yield_pages=sub)

    return m(got.old), m(got.new)


def version_number(key: str | None) -> int | None:
    try:
        return parse_key(key)[1] if key else None
    except ValueError:
        return None
