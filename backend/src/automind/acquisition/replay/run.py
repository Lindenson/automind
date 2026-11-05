"""Replay a reader or extractor version over stored pages and score it against gold (spec 011 FR-004, SC-001;
contracts/replay-cli.md, research R4).

Readers run offline: the CLI builds no search, fetch or model port and the socket guard is on while pages are read;
any network attempt aborts the replay. Rows are validated with the same pure checks research uses (imported from
`acquisition/pipeline/validate.py`, never copied). A reader version is a stored parser spec (`parser_versions`,
`km77@v2`; `km77@v1` falls back to config/site_readers.yaml while the database has no parser) or a candidate spec
from a JSON file, validated first (`<reader>@v<N>` as the file names it). Both run in the fixed interpreter.
Extractor replay needs model calls: only with `allow_llm`, at most `replay.extractor_max_pages` pages, outputs cached
in `extraction_cache` so a second replay of the same version costs nothing.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from automind.acquisition.domain import replay as scoring
from automind.acquisition.domain.versions import parse_key, prompt_key
from automind.acquisition.gold import repo as gold_repo
from automind.acquisition.parsing.spec import ParserSpec
from automind.acquisition.replay.offline import NetworkForbidden, no_network
from automind.acquisition.snapshots import store
from automind.acquisition.snapshots.store import SnapshotRef
from automind.application.ports import WebDoc
from automind.domain import evidence as ev
from automind.domain import specs
from automind.infrastructure import config
from automind.infrastructure.db import ExtractionCache, LLMCall, Variant, sessionmaker

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "orchestration" / "prompts"


class ReplayError(Exception):
    """A replay that cannot run; `code` is the CLI exit code (contracts/replay-cli.md)."""

    code = 1


class NoPages(ReplayError):
    code = 1


class InvalidSpec(ReplayError):
    code = 2


class Refused(ReplayError):
    code = 3


class NetworkAttempt(ReplayError):
    code = 4


class ReplayRequest(BaseModel):
    reader: str | None = None  # "km77@v1"
    reader_spec: str | None = None  # a candidate ParserSpec (JSON file), validated first
    extractor: str | None = None  # "extract_specs@v2"
    model: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    domains: list[str] | None = None
    attributes: list[str] | None = None
    limit_pages: int | None = None
    allow_llm: bool = False


class ReplayReport(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    version: str
    period: dict[str, str] | None = None
    pages: int
    pages_with_fields: int
    fields_per_page: float
    yield_: float = Field(alias="yield")
    rows_read: int
    rows_accepted: int
    pass_rate: float
    gold_covered: int
    gold_match: int
    accuracy: float | None
    accuracy_lb: float | None
    by_attribute: dict[str, dict[str, int]]
    mismatches: list[dict[str, Any]]
    duration_s: float = 0.0
    network_calls: int = 0
    llm_calls: int = 0

    def as_json(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")


# --- reader versions (spec 011 US4: parser specs) ------------------------------------------------------------------


async def resolve_reader(req: ReplayRequest) -> tuple[str, ParserSpec]:
    """(version key, spec): a stored version, its YAML v1 before the seed, or a validated candidate file."""
    from automind.acquisition.parsing import spec as ps  # noqa: PLC0415
    from automind.acquisition.parsing import store  # noqa: PLC0415
    from automind.acquisition.parsing.migrate_v1 import denylist, yaml_specs  # noqa: PLC0415

    if req.reader_spec:
        try:
            body = Path(req.reader_spec).read_text(encoding="utf-8")
        except OSError as e:
            raise InvalidSpec(f"{req.reader_spec}: {e}") from e
        errors = ps.check(body, denylist=denylist())
        if errors:
            raise InvalidSpec(f"{req.reader_spec}: " + "; ".join(errors))
        spec, _ = ps.parse(body)
        assert spec is not None
        return spec.key, spec
    assert req.reader is not None
    try:
        rid, version = parse_key(req.reader)
        stored = await store.version(req.reader)
    except ValueError as e:
        raise InvalidSpec(str(e)) from e
    if stored is not None:
        return stored.key, stored.spec
    if version == 1 and rid in (v1 := yaml_specs()):  # the database has no parser yet: today's YAML reader
        return req.reader, v1[rid]
    raise InvalidSpec(f"no parser version {req.reader!r}")


# --- validation: the research-time rules ------------------------------------------------------------------------


def _validate(c: Any, v: Variant | None, d: WebDoc, rules: dict[str, Any], excerpt_checked: bool) -> tuple[Any, ...]:
    from automind.acquisition.pipeline import validate as rs  # noqa: PLC0415 - the live rules

    if v is None:
        return c, *rs.check(c, d, None, None, excerpt_checked=excerpt_checked)
    c, bad = rs.sense_before(c, v, ev.classify_source(d.url), d.url)
    ctx = rs.plausibility_ctx(v, {})
    return c, *(bad or rs.check(c, d, ctx, rules, excerpt_checked=excerpt_checked))


def _values(
    ref: SnapshotRef, claims: list[Any], variants: dict[str, Variant], d: WebDoc, rules: dict[str, Any], checked: bool
) -> list[scoring.Value]:
    out = []
    for vid in ref.variant_ids or ("",):
        v = variants.get(vid)
        for c0 in claims:
            c, status, num, txt, _rule = _validate(c0, v, d, rules, checked)
            if status == "ACCEPTED" and c.attribute in specs.ATTRS:
                out.append(scoring.Value(ref.id, d.url, vid, c.attribute, num, txt, specs.ATTRS[c.attribute].unit,
                                         c.excerpt))  # fmt: skip
    return out


def read_page(
    ref: SnapshotRef, raw: bytes, spec: ParserSpec, variants: dict[str, Variant], rules: dict[str, Any],
    attributes: list[str] | None = None,
) -> scoring.PageResult:  # fmt: skip
    """One stored page through the parser spec and the live checks (pure apart from the research rule imports)."""
    from automind.acquisition.infrastructure.fetch import decode_body  # noqa: PLC0415
    from automind.acquisition.parsing import interpreter  # noqa: PLC0415
    from automind.acquisition.pipeline import validate as rs  # noqa: PLC0415

    url = ref.final_url or ref.url
    try:
        reading = interpreter.read(spec, decode_body(raw, None), url)
    except NetworkForbidden:
        raise
    except Exception:  # noqa: BLE001 - a broken page reads as nothing, as live
        reading = None
    if reading is None or reading.ambiguous:  # live: an ambiguous reading goes to the extractor instead
        return scoring.PageResult(ref.id, url, ref.variant_ids, 0, [])
    rows = [r for r in reading.rows if not attributes or r.attribute in attributes]
    claims = [rs.ReaderClaim(r.attribute, r.raw_value, r.raw_unit, r.excerpt) for r in rows]
    d = WebDoc(url, "", "", False)
    accepted = _values(ref, claims, variants, d, rules, True)
    return scoring.PageResult(ref.id, url, ref.variant_ids, len(rows), accepted, _read(ref, claims, d))


def _read(ref: SnapshotRef, claims: list[Any], d: WebDoc) -> list[scoring.Value]:
    """Every row as the reader read it, through the unit layer only (no sense or plausibility rule); a row the unit
    layer cannot read keeps its raw text, so it counts as wrong where gold exists."""
    from automind.acquisition.pipeline import validate as rs  # noqa: PLC0415

    out = []
    for vid in ref.variant_ids or ("",):
        for c in claims:
            status, num, txt, _ = rs.check(c, d, None, None, excerpt_checked=True)
            if status != "ACCEPTED":
                num, txt = None, " ".join(x for x in (c.raw_value, c.unit) if x)
            out.append(scoring.Value(ref.id, d.url, vid, c.attribute, num, txt, specs.ATTRS[c.attribute].unit,
                                     c.excerpt))  # fmt: skip
    return out


# --- shared ----------------------------------------------------------------------------------------------------


async def _variants(ids: set[str], have: dict[str, Variant]) -> None:
    missing = [i for i in ids if i and i not in have]
    if not missing:
        return
    async with sessionmaker()() as s:
        for v in (await s.execute(select(Variant).where(Variant.id.in_(missing)))).scalars():
            have[v.id] = v


async def _gold(variant_ids: set[str]) -> dict[tuple[str, str], scoring.Gold]:
    out: dict[tuple[str, str], scoring.Gold] = {}
    for vid in variant_ids:
        if not vid:
            continue
        for attr, g in gold_repo.best_by_attribute(await gold_repo.gold_for(vid)).items():
            out[(vid, attr)] = scoring.Gold(vid, attr, g.value_num, g.value_text, g.unit, g.tolerance,
                                            g.tolerance_kind, g.match_rule, g.dataset_id)  # fmt: skip
    return out


async def _llm_calls_since(t: datetime) -> int:
    async with sessionmaker()() as s:
        return int((await s.execute(select(func.count()).where(LLMCall.created_at >= t))).scalar_one())


PageFn = Callable[[list[SnapshotRef], dict[str, bytes], dict[str, Variant]], Awaitable[list[scoring.PageResult]]]


async def _corpus(req: ReplayRequest, domains: list[str] | None, limit: int | None, per_batch: PageFn) -> list[Any]:
    batch = int((config.acquisition_config().get("replay") or {}).get("batch", 500))
    pages: list[scoring.PageResult] = []
    variants: dict[str, Variant] = {}
    async for refs in store.iter_replayable(domains, req.since, req.until, batch):
        if limit is not None:
            refs = refs[: max(0, limit - len(pages))]
        if not refs:
            break
        bodies = await store.load_bodies(sorted({r.blob_sha256 for r in refs}))
        await _variants({v for r in refs for v in r.variant_ids}, variants)
        pages += await per_batch(refs, bodies, variants)
    return pages


# --- runs --------------------------------------------------------------------------------------------------------


async def _reader_pages(req: ReplayRequest) -> tuple[str, list[scoring.PageResult], int]:
    key, spec = await resolve_reader(req)
    rules = config.plausibility_rules()
    attempts = 0

    async def per_batch(refs: list[SnapshotRef], bodies: dict[str, bytes], variants: dict[str, Variant]) -> list[Any]:
        nonlocal attempts
        out = []
        with no_network() as guard:
            try:
                for r in refs:
                    if r.blob_sha256 in bodies:
                        out.append(read_page(r, bodies[r.blob_sha256], spec, variants, rules, req.attributes))
            except NetworkForbidden as e:
                raise NetworkAttempt(str(e)) from e
        attempts += guard.attempts
        if guard.attempts:
            raise NetworkAttempt(f"{guard.attempts} network attempt(s) while reading: {guard.last}")
        return out

    domains = req.domains or list(spec.domains)
    return key, await _corpus(req, domains, req.limit_pages, per_batch), attempts


def _prompt(key: str) -> tuple[str, str, str]:
    """(prompt name, prompt text, area) of an extraction prompt version; only the file's version before US5."""
    from automind.acquisition.pipeline.extract import PROMPT_FOR_AREA  # noqa: PLC0415

    try:
        name, _ = parse_key(key)
    except ValueError as e:
        raise InvalidSpec(str(e)) from e
    f = PROMPTS_DIR / f"{name}.md"  # read as data: the engine does not import the chat's orchestration
    text = f.read_text(encoding="utf-8").strip() if f.is_file() else None
    if text is None or prompt_key(text, name) != key:
        raise InvalidSpec(f"{key}: only the prompt file's current version exists before prompt versions (US5)")
    area = next((a for a, p in PROMPT_FOR_AREA.items() if p == name), None)
    if area is None:
        raise InvalidSpec(f"{key}: not an extraction prompt")
    return name, text, area


async def _extract_cached(doc: WebDoc, sha: str, name: str, text: str, area: str, model: str, target: str) -> Any:
    from automind.acquisition.pipeline import extract as extraction  # noqa: PLC0415
    from automind.infrastructure.adapters import LiveLLM  # noqa: PLC0415

    schema = extraction.schema_for(area)
    phash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    async with sessionmaker()() as s:
        hit = await s.get(ExtractionCache, (phash, model, sha, area))
    if hit is not None:
        return schema.model_validate(hit.output)
    out = await extraction.extract(LiveLLM(), {name: text}, area, target, doc)
    async with sessionmaker()() as s:
        row = {"prompt_hash": phash, "model": model, "blob_sha256": sha, "area": area,
               "output": out.model_dump(mode="json"), "created_at": datetime.now(UTC)}  # fmt: skip
        stmt = insert(ExtractionCache).values(**row)
        await s.execute(stmt.on_conflict_do_nothing())
        await s.commit()
    return out


async def _extractor_pages(req: ReplayRequest) -> tuple[str, list[scoring.PageResult], int]:
    if not req.allow_llm:
        raise Refused("extractor replay calls models: run it in the worker or pass --allow-llm")
    from automind.acquisition.infrastructure.pages import main_content  # noqa: PLC0415
    from automind.acquisition.pipeline import job as rs  # noqa: PLC0415
    from automind.infrastructure import llm_gateway  # noqa: PLC0415

    key = str(req.extractor)
    name, text, area = _prompt(key)
    model = llm_gateway.model_name("extractor")
    if req.model and req.model != model:
        raise Refused(f"model override {req.model} needs role model overrides (US5); the extractor runs {model}")
    cap = int((config.acquisition_config().get("replay") or {}).get("extractor_max_pages", 60))
    rules = config.plausibility_rules()

    async def per_batch(refs: list[SnapshotRef], bodies: dict[str, bytes], variants: dict[str, Variant]) -> list[Any]:
        from automind.acquisition.infrastructure.fetch import decode_body  # noqa: PLC0415

        out = []
        for r in refs:
            if r.blob_sha256 not in bodies:
                continue
            url = r.final_url or r.url
            title, body = main_content(decode_body(bodies[r.blob_sha256], None), url)
            d = WebDoc(url, title, body, False, snapshot_id=r.id)
            v = variants.get(r.variant_ids[0]) if r.variant_ids else None
            target = rs.target_of(v) if v is not None else "the vehicle on this page"
            got = await _extract_cached(d, r.blob_sha256, name, text, area, model, target)
            claims = [c for c in getattr(got, "claims", []) if not req.attributes or c.attribute in req.attributes]
            out.append(scoring.PageResult(r.id, url, r.variant_ids, len(claims),
                                          _values(r, claims, variants, d, rules, False)))  # fmt: skip
        return out

    limit = min(cap, req.limit_pages) if req.limit_pages else cap
    return f"{key}|{model}", await _corpus(req, req.domains, limit, per_batch), 0


async def run(req: ReplayRequest) -> ReplayReport:
    """Replay one version over the stored pages of the period; raises `ReplayError` (with its exit code)."""
    if sum(x is not None for x in (req.reader, req.reader_spec, req.extractor)) != 1:
        raise InvalidSpec("give exactly one of reader, reader_spec, extractor")
    started, t0 = datetime.now(UTC), time.monotonic()
    key, pages, attempts = await (_extractor_pages(req) if req.extractor else _reader_pages(req))
    if not pages:
        raise NoPages("no stored pages of this version's sites in the period")
    gold = await _gold({v for p in pages for v in p.variant_ids})
    period = None
    if req.since or req.until:
        period = ((req.since or started).date().isoformat(), (req.until or started).date().isoformat())
    rep = scoring.report(key, pages, gold, config.gold_tolerances(), period)
    return ReplayReport(**rep, duration_s=round(time.monotonic() - t0, 3), network_calls=attempts,
                        llm_calls=await _llm_calls_since(started))  # fmt: skip
