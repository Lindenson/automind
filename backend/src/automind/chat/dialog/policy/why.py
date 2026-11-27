"""Why a turn did what it did (spec 015 T223): the recorded passes of a turn as text — every rule asked, the one
that decided, the action and the node — and, after a replay, whether today's rules decide the same. Pure; the CLI
`delivery/cli/policy.py` and 013's `turn show` print it."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from automind.chat.dialog.policy.contracts import Decision
from automind.chat.domain.decision import DecisionRecord


def render_why(records: Sequence[DecisionRecord], replays: Mapping[int, Decision] | None = None) -> str:
    """The passes of one turn in order; `replays` (pass → today's decision) adds a same/differs line per pass."""
    if not records:
        return "no policy decisions recorded for this turn"
    lines = [f"turn {records[0].turn_id} (chat {records[0].chat_id}), rules {records[0].rules_version[:12]}"]
    for rec in sorted(records, key=lambda r: r.pass_no):
        lines.append(f"pass {rec.pass_no} on case v{rec.case_version}, config {rec.config_hash[:12]}:")
        lines += [f"  {'✓' if step.fired else '·'} {step.rule}: {step.why}" for step in rec.trail]
        lines.append(f"  → {rec.action.get('kind')} by {rec.decided_by}, next {rec.next_node}")
        if replays is not None and rec.pass_no in replays:
            lines.append(f"  replay: {_compare(rec, replays[rec.pass_no])}")
    return "\n".join(lines)


def _compare(rec: DecisionRecord, now: Decision) -> str:
    then = {k: v for k, v in rec.action.items() if k != "reason"}
    again = now.action.model_dump(mode="json", exclude={"reason"})
    if then == again and now.decided_by == rec.decided_by:
        return "same"
    return f"differs: today {now.action.kind} by {now.decided_by}"
