"""The extractor measured on stored pages (spec 011 US5): a prompt change with the old and new prompt text, a model
change with the old and new extractor model on the active extraction prompt. Calls go through `extraction_cache`
and are charged to the agent's budget before they run."""

from __future__ import annotations

from sqlalchemy import select

from automind.acquisition.domain import replay as scoring
from automind.acquisition.gates.application.measure_ports import Charge, NoMeasure
from automind.acquisition.gates.domain.change import Change
from automind.acquisition.gates.infrastructure import page_reading as pages
from automind.acquisition.infrastructure import config as acq_config
from automind.acquisition.infrastructure.fetch import decode_body
from automind.acquisition.infrastructure.pages import main_content
from automind.acquisition.parsing.extraction import areas
from automind.acquisition.pipeline.domain.target import target_of
from automind.acquisition.replay import run as replay
from automind.acquisition.snapshots.store import SnapshotRef
from automind.shared.contracts.llm import LLM
from automind.shared.contracts.web import WebDoc
from automind.shared.infrastructure.db.models import PromptVersion
from automind.shared.infrastructure.db.session import sessionmaker
from automind.shared.infrastructure.llm import gateway as llm_gateway

EST_EXTRACT_EUR = 0.002  # one extractor call on one page (flash-lite web reader)
EXTRACT_SPECS = "extract_specs"
ANY_VEHICLE = "the vehicle on this page"
Pair = tuple[list[scoring.PageResult], list[scoring.PageResult]]  # (old version, new version)


async def extractor_pair(c: Change, refs: list[SnapshotRef], *, llm: LLM | None = None,
                         charge: Charge | None = None) -> Pair:  # fmt: skip
    """(old, new) page results of the extractor. Raises `NoMeasure` when the prompt is not an extraction prompt or
    its versions are gone."""
    name, old_text, new_text, models = await _versions(c)
    area = next((a for a, p in areas.PROMPT_FOR_AREA.items() if p == name), None)
    if area is None:
        raise NoMeasure(f"{name} is not an extraction prompt")
    bodies, variants = await pages.bodies_and_variants(refs)
    rules = acq_config.plausibility_rules()
    old: list[scoring.PageResult] = []
    new: list[scoring.PageResult] = []
    for r in refs:
        if r.blob_sha256 not in bodies:
            continue
        url = r.final_url or r.url
        title, body = main_content(decode_body(bodies[r.blob_sha256], None), url)
        d = WebDoc(url, title, body, False, snapshot_id=r.id)
        v = variants.get(r.variant_ids[0]) if r.variant_ids else None
        target = target_of(v) if v is not None else ANY_VEHICLE
        for text, model, into in ((old_text, models[0], old), (new_text, models[1], new)):
            if charge is not None:
                await charge(EST_EXTRACT_EUR)
            token = llm_gateway.FORCED_MODELS.set({"extractor": model} if model else None)
            try:
                got = await replay.extract_cached(d, r.blob_sha256, name, text, area,
                                                  llm_gateway.model_name("extractor"), target, llm=llm)  # fmt: skip
            finally:
                llm_gateway.FORCED_MODELS.reset(token)
            claims = list(getattr(got, "claims", []))
            into.append(scoring.PageResult(r.id, url, r.variant_ids, len(claims),
                                           replay.accepted_values(r, claims, variants, d, rules, False)))  # fmt: skip
    return old, new


async def _versions(c: Change) -> tuple[str, str, str, tuple[str | None, str | None]]:
    """(prompt name, old text, new text, (old model, new model)) of a prompt or model change."""
    async with sessionmaker()() as s:
        if c.object_kind == "prompt":
            old = await s.get(PromptVersion, c.from_version) if c.from_version else None
            new = await s.get(PromptVersion, c.to_version)
            if old is None or new is None:
                raise NoMeasure(f"prompt versions of {c.object_key} not found")
            return c.object_key, old.text, new.text, (None, None)
        q = select(PromptVersion).where(PromptVersion.name == EXTRACT_SPECS, PromptVersion.status == "active")
        act = (await s.execute(q)).scalar_one()
    return EXTRACT_SPECS, act.text, act.text, (str(c.from_version), str(c.to_version))
