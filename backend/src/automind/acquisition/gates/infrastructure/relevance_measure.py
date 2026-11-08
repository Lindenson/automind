"""A relevance keyword change measured on stored pages (spec 011 US5 gap "manuales", research R14): the relevance
stage re-run with the old and the candidate keywords over the pages of the window that name the moved words. A page
counts when the old keywords give again its stored verdict; its values are read the live way — the running reader of
its site, offline, else the extractor through `extraction_cache` within the agent's budget — and checked against
the references. Implements `measure_ports.RelevanceMeasure`; the measure itself is `domain.relevance_change`."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from automind.acquisition.domain import relevance
from automind.acquisition.domain import replay as scoring
from automind.acquisition.gates.application.measure_ports import Charge
from automind.acquisition.gates.domain import relevance_change as rc
from automind.acquisition.gates.domain.change import Change
from automind.acquisition.gates.infrastructure import page_reading as pages
from automind.acquisition.gates.infrastructure.measure_extractor import ANY_VEHICLE, EST_EXTRACT_EUR, EXTRACT_SPECS
from automind.acquisition.gates.infrastructure.relevance_pages import Judged, judged, pages_text, references
from automind.acquisition.infrastructure import config as acq_config
from automind.acquisition.infrastructure import overrides
from automind.acquisition.infrastructure.fetch import decode_body
from automind.acquisition.infrastructure.pages import main_content
from automind.acquisition.pipeline.domain.target import target_of
from automind.acquisition.pipeline.relevance import relevance_target
from automind.acquisition.replay import run as replay
from automind.acquisition.replay.offline import no_network
from automind.acquisition.snapshots.store import SnapshotRef
from automind.shared.contracts.llm import LLM
from automind.shared.contracts.web import WebDoc
from automind.shared.infrastructure.config import loader as config
from automind.shared.infrastructure.db.models import Variant
from automind.shared.infrastructure.llm import gateway as llm_gateway

ValuesByPage = dict[tuple[str, str], list[scoring.Value]]


class RelevancePages:
    """The relevance keyword measure over the stored pages."""

    async def measure(self, c: Change, since: datetime, until: datetime, *, limit: int, llm: LLM | None = None,
                      charge: Charge | None = None) -> rc.RelevanceResult:  # fmt: skip
        """Re-judge the pages of [since, until] with the old and new keywords; check the moved pages' values."""
        before, after = rc.keyword_sets(c, relevance.KEYWORDS)
        items = await judged(since, until, words=rc.changed_words(c), limit=limit)
        texts, bodies = await pages_text([j.ref for j in items])
        vs: dict[str, Variant] = {}
        await replay.load_variants({j.variant_id for j in items}, vs)
        pairs, unreproduced = _rejudge(items, texts, vs, before, after)
        need = [j for j, p in pairs if rc.needs_values(p)]
        values = await _read_values(need, bodies, vs, llm=llm, charge=charge)
        refs = await references({j.variant_id for j in need})
        return rc.relevance_result([p for _, p in pairs], values, refs, unreproduced)


@contextmanager
def _keywords(lists: Mapping[str, Sequence[str]]) -> Iterator[None]:
    """The relevance rules with these keyword lists for the block (synchronous: no other task runs meanwhile)."""
    saved = {k: list(v) for k, v in relevance.KEYWORDS.items()}
    relevance.configure_keywords(lists)
    try:
        yield
    finally:
        relevance.configure_keywords(saved)


def _rejudge(items: Sequence[Judged], texts: Mapping[str, tuple[str, str]], vs: Mapping[str, Variant],
             before: Mapping[str, Sequence[str]], after: Mapping[str, Sequence[str]]
             ) -> tuple[list[tuple[Judged, rc.Rejudged]], int]:  # fmt: skip
    """The pages whose stored verdict the old keywords reproduce, with the new verdict; and how many did not."""
    gens = config.generations()
    out: list[tuple[Judged, rc.Rejudged]] = []
    unreproduced = 0
    for j in items:
        v, got = vs.get(j.variant_id), texts.get(j.ref.id)
        if v is None or got is None:
            continue
        tgt, generations = relevance_target(v, gens)
        facts = relevance.PageFacts(j.ref.final_url or j.ref.url, got[0], got[1])
        with _keywords(before):
            old = relevance.judge(facts, tgt, generations).verdict
        with _keywords(after):
            new = relevance.judge(facts, tgt, generations).verdict
        if old != j.verdict:
            unreproduced += 1
            continue
        out.append((j, rc.Rejudged(j.ref.id, j.variant_id, j.ref.domain, old, new)))
    return out, unreproduced


async def _read_values(items: Sequence[Judged], bodies: Mapping[str, bytes], vs: Mapping[str, Variant], *,
                       llm: LLM | None, charge: Charge | None) -> ValuesByPage:  # fmt: skip
    """(snapshot, variant) → the values the live path would accept from the page for the variant."""
    specs = await pages.running_specs()
    rules = acq_config.plausibility_rules()
    out: ValuesByPage = {}
    for j in items:
        raw = bodies.get(j.ref.blob_sha256)
        if raw is None:
            continue
        ref = SnapshotRef(j.ref.id, j.ref.url, j.ref.final_url, j.ref.domain, j.ref.fetched_at, j.ref.content_type,
                          (j.variant_id,), j.ref.blob_sha256)  # fmt: skip
        sp = pages.spec_for(specs, ref.domain)
        if sp is not None:
            with no_network():
                got = replay.read_page(ref, raw, sp, dict(vs), rules)
            if got.values or got.rows_read:
                out[(ref.id, j.variant_id)] = list(got.values)
                continue
        if charge is not None or llm is not None:
            out[(ref.id, j.variant_id)] = await _extracted(ref, raw, vs, rules, llm=llm, charge=charge)
    return out


async def _extracted(ref: SnapshotRef, raw: bytes, vs: Mapping[str, Variant], rules: dict[str, Any], *,
                     llm: LLM | None, charge: Charge | None) -> list[scoring.Value]:  # fmt: skip
    """The specs extractor on a page without a reader (cached; one call within the agent's budget)."""
    path = replay.PROMPTS_DIR / f"{EXTRACT_SPECS}.md"
    if not path.is_file():
        return []
    prompt = overrides.prompt_text(EXTRACT_SPECS, path.read_text(encoding="utf-8").strip())
    url = ref.final_url or ref.url
    title, body = main_content(decode_body(raw, None), url)
    d = WebDoc(url, title, body, False, snapshot_id=ref.id)
    v = vs.get(ref.variant_ids[0])
    target = target_of(v) if v is not None else ANY_VEHICLE
    if charge is not None:
        await charge(EST_EXTRACT_EUR)
    got = await replay.extract_cached(d, ref.blob_sha256, EXTRACT_SPECS, prompt, "specs",
                                      llm_gateway.model_name("extractor"), target, llm=llm)  # fmt: skip
    return replay.accepted_values(ref, list(got.claims) if got is not None else [], dict(vs), d, rules, False)
