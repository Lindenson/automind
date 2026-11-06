"""The extractor tuner (spec 011 US5 T107, research R13): a new extraction prompt version or a model for the
extractor role when the extractor's accuracy against gold falls, or when the configured extractor model changed.

- trigger (code): gold signals blamed to the extractor — accuracy of the last 7 days below the 30-day level by more
  than `gates.watch.accuracy_lb_drop` (with ≥ `MIN_SIGNALS` signals), or `models.yaml`'s extractor model differs from
  the one the tuner last saw; `{"force": true}` runs it anyway (owner, tests);
- context (code): the active prompt version (body without its header), up to 8 mismatches with their excerpts and
  gold values, the allowed models with their price per 1k tokens (config/prices.yaml);
- propose (role `extractor_tuner`, a web reader with no tools; excerpts only inside <untrusted_document>): edits as
  {find, replace} on the active text — applied by code, each `find` must occur exactly once — or a model from
  `allowed_models`;
- code builds a `PromptProposal` (diff on the active version; the header is written by the journal) or a
  `ModelProposal`, checks it with the levers and journals it; the gates decide.
Budget: `agents.budgets.extractor_tuner` and `max_runs_per_day`.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel, Field

from automind.acquisition.agents import budget as budgets
from automind.acquisition.agents.levers import ModelProposal, PromptProposal

log = logging.getLogger(__name__)
AGENT = ROLE = "extractor_tuner"
PROMPT = Path(__file__).resolve().parents[2] / "orchestration" / "prompts" / "extractor_tuner.md"
EST_EUR = 0.004
MIN_SIGNALS = 10
MAX_MISMATCHES = 8
T = TypeVar("T", bound=BaseModel)
_HEADER = re.compile(r"^\s*<!--.*?-->\s*\n?", re.S)
_COMPONENT = re.compile(r"^extractor:([a-z_]+)@")


class LLM(Protocol):
    async def structured(self, role: str, schema: type[T], system: str, user: str) -> T: ...


class GatewayLLM:
    async def structured(self, role: str, schema: type[T], system: str, user: str) -> T:
        from automind.infrastructure import llm_gateway  # noqa: PLC0415

        return await llm_gateway.structured(role, schema, system, user)


LLM_OVERRIDE: LLM | None = None


class Edit(BaseModel):
    find: str = Field(min_length=3, max_length=600)
    replace: str = Field(max_length=2000)


class TunerOut(BaseModel):
    kind: Literal["prompt", "model", "none"]
    edits: list[Edit] = Field(default_factory=list, max_length=10)
    model: str | None = None
    explanation: str = Field(default="", max_length=300)


# --- pure ---------------------------------------------------------------------------------------------------------


def body_of(text: str) -> str:
    """The prompt without its header comment (the header is code's)."""
    return _HEADER.sub("", text, count=1).strip()


def apply_edits(text: str, edits: list[Edit]) -> tuple[str | None, list[str]]:
    """The text with each edit applied in turn; every `find` must occur exactly once."""
    errs = []
    for i, e in enumerate(edits, 1):
        n = text.count(e.find)
        if n != 1:
            errs.append(f"edit {i}: the passage occurs {n} times (must be exactly once)")
            continue
        text = text.replace(e.find, e.replace, 1)
    return (None if errs or not edits else text), errs


def degraded(acc7: float | None, acc30: float | None, n7: int, drop: float) -> bool:
    return n7 >= MIN_SIGNALS and acc7 is not None and acc30 is not None and acc7 < acc30 - drop


def price_lines(allowed: list[str], prices: dict[str, Any]) -> list[str]:
    out = []
    for m in allowed:
        p = (prices.get("llm") or {}).get(m) or prices.get("default_llm") or {}
        out.append(f"{m}: input €{float(p.get('input', 0)) / 1000:.5f}, output €{float(p.get('output', 0)) / 1000:.5f}"
                   " per 1k tokens")  # fmt: skip
    return out


def user_message(name: str, key: str, body: str, mismatches: list[dict[str, Any]], current_model: str,
                 models: list[str], why: str) -> str:  # fmt: skip
    docs = "\n".join(
        f"- {m['attribute']}: extracted {m['ours']}, reference {m['gold']} {m.get('unit') or ''}\n"
        f'<untrusted_document url="{m.get("url") or ""}">\n{str(m.get("excerpt") or "")[:300]}\n</untrusted_document>'
        for m in mismatches
    )  # fmt: skip
    return (f"Why now: {why}\nExtractor model: {current_model}\nModels you may choose (prices):\n"
            + "\n".join(models) + f"\n\nActive prompt {key} ({name}):\n<<<\n{body}\n>>>\n\n"
            f"Disagreements with reference values:\n{docs or 'none recorded'}")  # fmt: skip


# --- database and the task ----------------------------------------------------------------------------------------


_ACC = """
SELECT coalesce(sum(CASE WHEN verdict = 'right' THEN 1 ELSE 0 END), 0),
       coalesce(sum(CASE WHEN verdict = 'wrong' THEN 1 ELSE 0 END), 0)
FROM truth_signals WHERE kind = 'gold' AND component LIKE 'extractor:%' AND created_at >= :since
"""
_MISMATCHES = """
SELECT t.component, t.attribute, c.value_num, c.excerpt, g.value_num, g.unit, e.url
FROM truth_signals t
LEFT JOIN claims c ON c.id = t.claim_id
LEFT JOIN gold_values g ON g.id = t.gold_id
LEFT JOIN evidence e ON e.id = c.evidence_id
WHERE t.kind = 'gold' AND t.verdict = 'wrong' AND t.component LIKE 'extractor:%' AND t.created_at >= :since
ORDER BY t.created_at DESC LIMIT :n
"""


async def _acc(since: datetime) -> tuple[float | None, int]:
    from sqlalchemy import text  # noqa: PLC0415

    from automind.infrastructure.db import sessionmaker  # noqa: PLC0415

    async with sessionmaker()() as s:
        right, wrong = (int(x) for x in (await s.execute(text(_ACC), {"since": since})).one())
    n = right + wrong
    return (right / n if n else None), n


async def mismatches(since: datetime, n: int = MAX_MISMATCHES) -> list[dict[str, Any]]:
    from sqlalchemy import text  # noqa: PLC0415

    from automind.infrastructure.db import sessionmaker  # noqa: PLC0415

    async with sessionmaker()() as s:
        rows = (await s.execute(text(_MISMATCHES), {"since": since, "n": n})).all()
    return [{"component": comp, "attribute": a, "ours": ours, "excerpt": x, "gold": g, "unit": u, "url": url}
            for comp, a, ours, x, g, u, url in rows]  # fmt: skip


async def _last_model() -> str | None:
    from sqlalchemy import text  # noqa: PLC0415

    from automind.infrastructure.db import sessionmaker  # noqa: PLC0415

    q = text("SELECT result->>'model' FROM acq_tasks WHERE kind = :k AND state = 'done' AND result ? 'model' "
             "ORDER BY finished_at DESC LIMIT 1")  # fmt: skip
    async with sessionmaker()() as s:
        return (await s.execute(q, {"k": AGENT})).scalar()


async def why_now(payload: dict[str, Any], now: datetime, current_model: str) -> str | None:
    from automind.acquisition.domain.gates import GateConfig  # noqa: PLC0415
    from automind.acquisition.infrastructure.config import agents_config  # noqa: PLC0415

    if payload.get("force"):
        return str(payload.get("reason") or "requested")
    last = await _last_model()
    if last is not None and last != current_model:
        return f"the extractor model changed from {last} to {current_model}"
    acc7, n7 = await _acc(now - timedelta(days=7))
    acc30, _ = await _acc(now - timedelta(days=30))
    drop = GateConfig.from_mapping(agents_config()).watch_accuracy_lb_drop
    if degraded(acc7, acc30, n7, drop):
        return f"extractor accuracy against gold {acc7:.2f} in 7 days vs {acc30:.2f} in 30 days ({n7} signals)"
    return None


async def run_tuner(payload: dict[str, Any], *, llm: LLM | None = None, charge: Any = None,
                    now: datetime | None = None) -> dict[str, Any]:  # fmt: skip
    from sqlalchemy import select  # noqa: PLC0415

    from automind.acquisition.gates import journal  # noqa: PLC0415
    from automind.acquisition.infrastructure.config import agents_config
    from automind.acquisition.worker.budget import BudgetExceeded  # noqa: PLC0415
    from automind.infrastructure import llm_gateway  # noqa: PLC0415
    from automind.infrastructure.config import prices  # noqa: PLC0415
    from automind.infrastructure.db import PromptVersion, sessionmaker  # noqa: PLC0415

    now = now or datetime.now(UTC)
    current_model = llm_gateway.model_name("extractor")
    why = await why_now(payload, now, current_model)
    if why is None:
        return {"skipped": "no trigger", "model": current_model}
    found = await mismatches(now - timedelta(days=30))
    names = [m.group(1) for x in found if (m := _COMPONENT.match(str(x["component"] or "")))]
    name = str(payload.get("prompt") or (max(set(names), key=names.count) if names else "extract_specs"))
    async with sessionmaker()() as s:
        active = (
            await s.execute(select(PromptVersion).where(PromptVersion.name == name, PromptVersion.status == "active"))
        ).scalar_one_or_none()
    if active is None:
        return {"skipped": f"no active version of {name}", "model": current_model}
    body = body_of(active.text)
    allowed = [str(m) for m in agents_config().get("allowed_models") or []]
    user = user_message(name, active.key, body, [x for x in found if (x["component"] or "").startswith(
        f"extractor:{name}@")] or found, current_model, price_lines(allowed, prices()), why)  # fmt: skip
    try:
        if charge is not None:
            await charge(EST_EUR)
        ans = await (llm or LLM_OVERRIDE or GatewayLLM()).structured(ROLE, TunerOut, PROMPT.read_text("utf-8"), user)
    except BudgetExceeded:
        return {"stop": "budget", "model": current_model}
    except Exception as e:  # noqa: BLE001 - a failed call ends this run
        return {"stop": f"model call failed ({type(e).__name__})", "model": current_model}
    out: dict[str, Any] = {"why": why, "kind": ans.kind, "prompt": name, "model": current_model}
    evidence = {"trigger": why, "mismatches": found[:MAX_MISMATCHES], "explanation": ans.explanation}
    proposal: PromptProposal | ModelProposal
    if ans.kind == "prompt":
        text, errs = apply_edits(body, ans.edits)
        if text is None:
            return {**out, "refused": errs or ["no edit"]}
        proposal = PromptProposal(name=name, text=text, base_key=active.key)
    elif ans.kind == "model" and ans.model:
        proposal = ModelProposal(role="extractor", model=ans.model)
    else:
        return {**out, "refused": ["no change proposed"]}
    errs = await journal.check(AGENT, proposal)
    if errs:
        return {**out, "refused": errs}
    out["change_id"] = await journal.propose(AGENT, proposal, why.split(" ")[0] if why else "tuning", evidence)
    return out


async def handle(payload: dict[str, Any], *, guard: Any = None, llm: LLM | None = None) -> dict[str, Any]:
    if why := await budgets.stop_reason(AGENT):
        return {"skipped": why}
    return await run_tuner(payload, llm=llm, charge=guard.charge if guard is not None else None)
