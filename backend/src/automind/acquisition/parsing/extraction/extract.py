"""The extractor, relevance and validator calls (web readers: text in, structured out, no tools; R8, constitution
VIII, XI). Pages whose variant match is uncertain go to the validator role: only SAME_VARIANT claims are kept as
variant values. Errors: the model gateway's own (budget, provider) propagate to the stage that called.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from automind.acquisition.parsing.extraction.areas import AREA_ATTRS, PROMPT_FOR_AREA, schema_for
from automind.acquisition.parsing.extraction.contracts import RelevanceOut, Verdicts
from automind.acquisition.parsing.normalise.text import folded
from automind.shared import evidence as ev
from automind.shared.contracts.llm import LLM
from automind.shared.contracts.web import WebDoc


def excerpt_in_doc(excerpt: str, doc_text: str, must_contain: str | None = None) -> bool:
    """The excerpt must literally occur in the document (≥15 chars), and contain `must_contain` if given."""
    ex = folded(excerpt)
    if len(ex) < 15 or not ev.occurs(excerpt, doc_text):
        return False
    return must_contain is None or ev.validate_excerpt(excerpt, must_contain, doc_text)


def user_prompt(area: str, target: str, doc: WebDoc) -> str:
    """The extractor's user message: the target, the area, its allowed attributes and the untrusted document."""
    allowed = ", ".join(AREA_ATTRS.get(area, [])) or "(see schema)"
    return (
        f"Target: {target}\nArea: {area}\nAllowed attributes: {allowed}\n\n"
        f'<untrusted_document url="{doc.url}">\n{doc.title}\n{doc.text}\n</untrusted_document>'
    )


async def extract(llm: LLM, prompts: dict[str, str], area: str, target: str, doc: WebDoc) -> BaseModel:
    """The area's items from one document, by the area's versioned prompt (`prompts` by name)."""
    return await llm.structured(
        "extractor", schema_for(area), prompts[PROMPT_FOR_AREA[area]], user_prompt(area, target, doc)
    )


async def judge_relevance(llm: LLM, prompt: str, target: str, doc: WebDoc) -> RelevanceOut:
    """Whether the document is about the target car (first 3000 characters), for pages the rules cannot decide."""
    return await llm.structured(
        "relevance",
        RelevanceOut,
        prompt,
        f"Target: {target}\n\n"
        f'<untrusted_document url="{doc.url}">\n{doc.title}\n{doc.text[:3000]}\n</untrusted_document>',
    )


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
