"""Area extraction schemas and calls (web readers: text in, structured out, no tools; R8, constitution VIII).

Every extracted item carries a verbatim excerpt that code checks against the document
(`domain.evidence.validate_excerpt`). Pages whose variant match is uncertain go to the validator
role (constitution XI): only SAME_VARIANT claims are kept as variant values.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Literal

from pydantic import BaseModel, Field, create_model

from automind.application.ports import LLM, WebDoc
from automind.domain import evidence as ev
from automind.domain import specs

AREA_ATTRS: dict[str, list[str]] = {
    "specs": [k for k, a in specs.ATTRS.items() if a.category == "specs"],
    "engineering": [k for k, a in specs.ATTRS.items() if a.category == "engineering"],
    "measured": [k for k, a in specs.ATTRS.items() if a.category == "measured"],
    "price": ["official_price_es"],
    "maintenance": ["service_interval_km", "service_interval_months"],
}
SPEC_AREAS = ("specs", "engineering", "measured", "price")
PROMPT_FOR_AREA = {
    "used_price": "extract_used_price",
    "specs": "extract_specs",
    "engineering": "extract_specs",
    "measured": "extract_specs",
    "price": "extract_specs",
    "maintenance": "extract_maintenance",
    "reviews": "extract_reviews",
    "reliability": "extract_reliability",
    "used_issues": "extract_reliability",
    "manufacturer": "extract_manufacturer",
}


class _Excerpted(BaseModel):
    excerpt: str = Field(description="Verbatim sentence or table row from the document (copy exactly, ≤300 chars)")


def spec_claims_schema(area: str) -> type[BaseModel]:
    keys = tuple(AREA_ATTRS[area])
    claim = create_model(
        f"SpecClaim_{area}",
        __base__=_Excerpted,
        attribute=(Literal[keys], ...),  # type: ignore[valid-type]
        raw_value=(str, Field(description="Value exactly as written, e.g. '245 CV', '1.430', '6,2'")),
        unit=(str | None, Field(description="Unit as written, e.g. 'CV', 'kW', 'Nm', 'kg', 's', 'mm', 'EUR'")),
        scope=(
            Literal["VARIANT", "GENERATION", "ENGINE"],
            Field(description="VARIANT if stated for this exact variant"),
        ),
    )
    return create_model(
        f"SpecClaims_{area}",
        is_about_variant=(bool, Field(description="False if the document is about a different car/generation")),
        claims=(list[claim], ...),  # type: ignore[valid-type]
    )


class MaintenanceEntry(_Excerpted):
    item: str
    interval_km: str | None = Field(default=None, description="As written, e.g. '15.000 km'")
    interval_months: str | None = Field(default=None, description="As written, e.g. '12 meses', '2 years'")
    cost_eur: str | None = Field(default=None, description="As written, only if the document states a cost")


class MaintenanceItems(BaseModel):
    is_about_variant: bool
    items: list[MaintenanceEntry]


class ReviewEntry(_Excerpted):
    polarity: Literal["PRO", "CON"]
    tag: Literal["comfort", "handling", "quality", "practicality", "noise", "reliability", "value", "other"]
    reviewer: Literal["EXPERT", "OWNER"]
    text: str = Field(description="Neutral paraphrase, ≤25 words")


class ReviewItems(BaseModel):
    is_about_variant: bool
    items: list[ReviewEntry]


class IssueEntry(_Excerpted):
    component: str
    description: str
    age_from: int | None = None
    age_to: int | None = None
    mileage_from: int | None = None
    mileage_to: int | None = None
    severity_hint: str = Field(default="", description="The document's own wording about seriousness")


class StatEntry(_Excerpted):
    source: str
    metric: str
    value: str
    year: int | None = None


class IssueItems(BaseModel):
    is_about_variant: bool
    issues: list[IssueEntry]
    stats: list[StatEntry] = Field(default_factory=list)


class ManufacturerEntry(_Excerpted):
    fact_type: Literal["HISTORY", "KEY_MODEL", "MARKET_POSITION"]
    text: str
    positioning: Literal["PREMIUM", "MAINSTREAM", "BUDGET"] | None = None


class ManufacturerFacts(BaseModel):
    is_about_variant: bool = True
    facts: list[ManufacturerEntry]


class UsedPriceEntry(_Excerpted):
    model_year_from: int | None = None
    model_year_to: int | None = None
    min: float
    max: float
    currency: Literal["EUR", "GBP", "USD"] = "EUR"
    market: Literal["ES", "GB", "DE", "US"] = "ES"
    quoted_on: str | None = None


class UsedPriceItems(BaseModel):
    is_about_variant: bool = True
    ranges: list[UsedPriceEntry] = Field(default_factory=list)


def schema_for(area: str) -> type[BaseModel]:
    if area in SPEC_AREAS:
        return spec_claims_schema(area)
    return {
        "maintenance": MaintenanceItems,
        "reviews": ReviewItems,
        "reliability": IssueItems,
        "used_issues": IssueItems,
        "manufacturer": ManufacturerFacts,
        "used_price": UsedPriceItems,
    }[area]


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKC", t).lower().replace(" ", " ")
    return re.sub(r"\s+", " ", t).strip()


def excerpt_in_doc(excerpt: str, doc_text: str, must_contain: str | None = None) -> bool:
    """The excerpt must literally occur in the document (≥15 chars), and contain `must_contain` if given."""
    ex = _norm(excerpt)
    if len(ex) < 15 or ex not in _norm(doc_text):
        return False
    return must_contain is None or ev.validate_excerpt(excerpt, must_contain, doc_text)


def user_prompt(area: str, target: str, doc: WebDoc) -> str:
    allowed = ", ".join(AREA_ATTRS.get(area, [])) or "(see schema)"
    return (
        f"Target: {target}\nArea: {area}\nAllowed attributes: {allowed}\n\n"
        f'<untrusted_document url="{doc.url}">\n{doc.title}\n{doc.text}\n</untrusted_document>'
    )


async def extract(llm: LLM, prompts: dict[str, str], area: str, target: str, doc: WebDoc) -> BaseModel:
    return await llm.structured(
        "extractor", schema_for(area), prompts[PROMPT_FOR_AREA[area]], user_prompt(area, target, doc)
    )


# --- relevance role (spec 003 FR-013): only for pages the rules cannot decide -------------------


class RelevanceOut(BaseModel):
    verdict: Literal["RELEVANT", "MULTI_VARIANT", "OTHER_VARIANT", "NOT_ABOUT_CAR"]
    other: str | None = None
    reason: str = ""


async def judge_relevance(llm: LLM, prompt: str, target: str, doc: WebDoc) -> RelevanceOut:
    return await llm.structured(
        "relevance",
        RelevanceOut,
        prompt,
        f"Target: {target}\n\n"
        f'<untrusted_document url="{doc.url}">\n{doc.title}\n{doc.text[:3000]}\n</untrusted_document>',
    )


# --- validator role (constitution XI) -----------------------------------------------------------


class Verdict(BaseModel):
    index: int
    verdict: Literal["SAME_VARIANT", "GENERATION_WIDE", "OTHER_VARIANT", "OTHER_MARKET", "OTHER_YEAR", "UNCLEAR"]
    reason: str = ""


class Verdicts(BaseModel):
    verdicts: list[Verdict]


async def validate_claims(
    llm: LLM, prompt: str, target: str, doc: WebDoc, claims: list[dict[str, Any]]
) -> dict[int, str]:
    """Ask the validator about each claim; missing verdicts count as UNCLEAR."""
    lines = "\n".join(
        f"{i}. {c.get('label', '')}: {c.get('value', '')} — “{c.get('excerpt', '')}”" for i, c in enumerate(claims)
    )
    out = await llm.structured(
        "validator",
        Verdicts,
        prompt,
        f"Target variant: {target}\n\nClaims:\n{lines}\n\n"
        f'<untrusted_document url="{doc.url}">\n{doc.title}\n{doc.text[:6000]}\n</untrusted_document>',
    )
    got = {v.index: v.verdict for v in out.verdicts}
    return {i: got.get(i, "UNCLEAR") for i in range(len(claims))}
