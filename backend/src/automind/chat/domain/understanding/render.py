"""A turn's understanding as text for a person reading a complaint (spec 013 T035): what came in, what the model
read, what code dropped and corrected, the intent, and what the old interpreter read during the shadow; empty fields
are left out. Pure."""

from __future__ import annotations

import json

from automind.chat.domain.understanding.record import UnderstandingRecord


def render_understanding(rec: UnderstandingRecord | None) -> str:
    """The record as indented sections; a line saying so when the turn has none."""
    if rec is None:
        return "no understanding recorded for this turn"
    q = rec.input.get("question")
    head = f"turn {rec.turn_id} (chat {rec.chat_id}), source {rec.source}"
    lines = [head + (", the same question as the turn before" if rec.question_repeated else "")]
    lines.append("input: " + _json({k: v for k, v in rec.input.items() if k != "question"}))
    lines.append("open question: " + (_json(q) if q else "none"))
    if rec.model or rec.model_raw is not None:
        lines.append(f"model {rec.model}, prompt {rec.prompt_version}, {rec.latency_ms} ms:")
        lines.append("  " + _json(rec.model_raw))
    if rec.refused:
        lines.append(f"refused: {rec.refused}")
    lines += ["dropped:", *(f"  {d.check} {d.field}: {d.why}" for d in rec.rejected)] if rec.rejected else []
    lines += ["overrides:", *(f"  {o.rule} {o.field}: {_json(o.before)} → {_json(o.after)} ({o.why})"
                              for o in rec.overrides)] if rec.overrides else []  # fmt: skip
    lines.append("intent: " + (_json(rec.intent) if rec.intent is not None else "none"))
    if rec.old_reading is not None:
        lines.append("old interpreter (decided the turn): " + _json(rec.old_reading))
    return "\n".join(lines)


def _json(value: object) -> str:
    return json.dumps(_compact(value), ensure_ascii=False, sort_keys=True)


def _compact(value: object) -> object:
    """`value` without its empty parts (None, "", [], {}, false at any depth): a model dump keeps every default,
    which hides the few fields that say something."""
    if isinstance(value, dict):
        kept = {k: _compact(v) for k, v in value.items()}
        return {k: v for k, v in kept.items() if v not in (None, "", [], {}, False)}
    if isinstance(value, list):
        return [_compact(v) for v in value]
    return value
