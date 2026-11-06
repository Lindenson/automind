"""S4 relevance (spec 011 strangler, research R5): is a page about the job's car? Rules first (generation, years,
variant, fuel, body, gearbox, drive), the relevance role for uncertain pages within a per-job allowance; the verdict
is stored per page and variant. Moved from `application/research.py` with the bodies unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from automind.acquisition.pipeline import extract as ex
from automind.acquisition.pipeline import stamp
from automind.acquisition.pipeline.plan import known_makes
from automind.acquisition.pipeline.validate import _variant_gearbox, fuel_of
from automind.acquisition.ports import AcqPorts
from automind.application.usage import BudgetExceeded
from automind.domain import relevance as rel
from automind.infrastructure import db
from automind.shared.contracts.web import Page

VERSION = "relevance@2"  # 2: a model named by its local (Chinese) names (chat 2026-11-06)


MAX_LLM_RELEVANCE_PER_JOB = 4


SERVICE_AREAS = ("maintenance",)  # brand-wide service pages count (spec 009 FR-020); warranty is a BRAND_AREA


LLM_PER_JOB = 6  # default; config/search.yaml concurrency.llm_per_job


def _llm_per_job(ports: AcqPorts) -> int:
    return int(((ports.ref.search or {}).get("concurrency") or {}).get("llm_per_job", LLM_PER_JOB))


def _relevance_target(v: db.Variant, ports: AcqPorts) -> tuple[rel.Target, list[rel.GenerationInfo]]:
    aliases = getattr(ports.ref, "aliases", None)
    names = aliases.names_of(v.make, v.model) if hasattr(aliases, "names_of") else []
    return relevance_target(v, ports.ref.generations, names)


def relevance_target(v: db.Variant, generations: Mapping[str, Sequence[tuple[str, int | None, int | None]]],
                     names: Sequence[str] = ()) -> tuple[rel.Target, list[rel.GenerationInfo]]:  # fmt: skip
    """The relevance rules' target and the model's known generations (live, and the offline relevance measure)."""
    gens = [rel.GenerationInfo(g, a, b) for g, a, b in generations.get(f"{v.make}|{v.model}", [])]
    if v.generation and not any(g.code == v.generation for g in gens):
        gens.append(rel.GenerationInfo(v.generation, v.generation_years_from, v.generation_years_to))
    tgt = rel.Target(v.make, v.model, v.generation, v.generation_years_from, v.generation_years_to,
                     v.variant_name, fuel_of(v.variant_name, v.powertrain), v.body_class,
                     v.transmission or _variant_gearbox(v), v.drive, tuple(names))  # fmt: skip
    return tgt, gens


class _PageJudge:
    """Relevance of one page: rules first, the relevance role for uncertain pages (at most
    MAX_LLM_RELEVANCE_PER_JOB per job). Safe to call concurrently: the budget is taken before any await."""

    def __init__(self, ports: AcqPorts, v: db.Variant, tgt: rel.Target, gens: list[rel.GenerationInfo], target: str,
                 area: str | None = None):  # fmt: skip
        self.ports, self.v, self.tgt, self.gens, self.target = ports, v, tgt, gens, target
        self.service = area in SERVICE_AREAS
        self.llm_left = MAX_LLM_RELEVANCE_PER_JOB if "relevance" in ports.ref.prompts else 0

    async def __call__(self, p: Page) -> rel.Relevance:
        facts = rel.PageFacts(p.url, p.title, p.text)
        if self.service:  # spec 009 FR-020: the brand's service and warranty pages apply to the car
            r = rel.judge_service(facts, self.tgt, self.gens, known_makes(self.ports))
        else:
            r = rel.judge(facts, self.tgt, self.gens)
        method = "RULES"
        if r.verdict == "UNCERTAIN" and self.llm_left > 0:
            self.llm_left -= 1
            try:
                out = await ex.judge_relevance(
                    self.ports.llm, self.ports.ref.prompts["relevance"], self.target, p.as_doc()
                )
                r, method = rel.Relevance(out.verdict, out.reason or "relevance check", out.other), "LLM"
            except BudgetExceeded:
                raise
            except Exception:  # noqa: BLE001 - no answer: stays uncertain, the validator decides per claim
                pass
        await _store_relevance(p, self.v.id, r, method)
        return r


async def _store_relevance(p: Page, variant_id: str, r: rel.Relevance, method: str) -> None:
    if p.document_id is None:
        return
    from sqlalchemy.dialects.postgresql import insert  # noqa: PLC0415

    values = {"document_id": p.document_id, "variant_id": variant_id, "verdict": r.verdict,
              "other": (r.other or "")[:80] or None, "reason": r.reason, **stamp.relevance(method)}  # fmt: skip
    async with db.sessionmaker()() as s:
        stmt = insert(db.PageRelevance).values(**values)
        await s.execute(stmt.on_conflict_do_update(index_elements=["document_id", "variant_id"], set_=values))
        await s.commit()
