"""A change to an engine object as the gates see it (spec 011 US5, FR-019, research R14-R15): the plain record of an
`acq_changes` row, and the pure rules around it — who proposed it, the gate results it carries, its one-sentence
explanation, the period its replay corpus covers, how long it has waited, what a candidate version is called."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from automind.acquisition.domain import gates, relevance_audit
from automind.shared.contracts.json import JsonObject

AGENT = "agent:"
OPEN = (
    gates.ChangeStatus.PROPOSED,
    gates.ChangeStatus.REPLAY,
    gates.ChangeStatus.SHADOW,
    gates.ChangeStatus.WATCH,
)  # statuses a gate may still close
WINDOW_DAYS = 30  # the replay corpus: the object's pages of the last month up to the change's `as_of`
VERSION_CHARS = 80  # the version columns


@dataclass(frozen=True)
class Change:
    """One `acq_changes` row."""

    id: str
    author: str  # agent:<name> | system | owner
    object_kind: str  # a gates.ObjectKind value
    object_key: str
    from_version: str | None
    to_version: str | None
    status: str  # a gates.ChangeStatus value
    diff: JsonObject = field(default_factory=dict)
    diff_hash: str = ""
    reason: str = ""
    evidence: JsonObject = field(default_factory=dict)
    gates: JsonObject = field(default_factory=dict)
    explanation: str = ""
    created_at: datetime | None = None
    closed_at: datetime | None = None
    metrics_before: JsonObject | None = None

    @property
    def agent(self) -> str:
        """The proposing agent's name (the author without `agent:`)."""
        return self.author.removeprefix(AGENT)

    @property
    def open(self) -> bool:
        """Not closed yet."""
        return self.closed_at is None


def metrics_of(c: Change, gate: str, which: str = "metrics_new") -> gates.Metrics | None:
    """The metrics a gate recorded (`metrics_new` or `metrics_old`), None when it recorded none."""
    got = (c.gates.get(gate) or {}).get(which)
    return gates.Metrics.from_report(got) if got else None


def sentence(c: Change, status: str | None = None, gate: str | None = None, verdict: gates.Verdict | None = None,
             wrong_signals: int = 0, days: float | None = None) -> str:  # fmt: skip
    """The change's one-sentence explanation in `status` (its own when None), e.g. "km77 parser v4→v5: …"."""
    old, new = metrics_of(c, "shadow", "metrics_old"), metrics_of(c, "shadow")
    shadow = (old, new) if old is not None and new is not None else None
    return gates.explain(_facts(c, status, gate), replay=metrics_of(c, "replay"), shadow=shadow, verdict=verdict,
                         wrong_signals=wrong_signals, days=days)  # fmt: skip


def with_gate(c: Change, gate: str, verdict: gates.Verdict, old: gates.Metrics | None, new: gates.Metrics | None,
              at: datetime, extra: JsonObject | None = None) -> JsonObject:  # fmt: skip
    """The change's gate results with this gate's verdict, metrics and time."""
    out = dict(c.gates)
    out[gate] = {**verdict.as_dict(), "metrics_old": old.as_dict() if old else None,
                 "metrics_new": new.as_dict() if new else None, "at": at.isoformat(), **(extra or {})}  # fmt: skip
    return out


def accepted_at(c: Change, now: datetime) -> datetime:
    """When the change was accepted (its creation, else now, when the record lacks it)."""
    at = (c.gates.get("accept") or {}).get("at")
    return datetime.fromisoformat(at) if at else (c.created_at or now)


def waited_days(c: Change, now: datetime) -> float:
    """Days since the change was proposed."""
    return max(0.0, (now - c.created_at).total_seconds() / 86400) if c.created_at else 0.0


def day_of(value: object) -> datetime | None:
    """An evidence date (`as_of`, `changed_on`): a datetime as is, an ISO day at midnight UTC, None when absent."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.combine(date.fromisoformat(str(value)[:10]), time.min, tzinfo=UTC)


def corpus_window(c: Change, now: datetime) -> tuple[datetime, datetime]:
    """[since, until) of the replay corpus: `WINDOW_DAYS` up to `as_of`, extended by the days the change waited."""
    as_of = day_of(c.evidence.get("as_of")) or now
    since = as_of - timedelta(days=WINDOW_DAYS)
    return since, min(now, as_of + timedelta(days=1 + int(waited_days(c, now))))


def component_like(c: Change) -> str | None:
    """The `truth_signals.component` pattern of the change's new version (research R9 keys), None for a source."""
    match c.object_kind:
        case gates.ObjectKind.PARSER:
            return f"parser:{c.to_version}"
        case gates.ObjectKind.PROMPT:
            return f"extractor:{c.to_version}|%"
        case gates.ObjectKind.ROLE_MODEL:
            return f"extractor:%|{c.to_version}"
        case gates.ObjectKind.RULE:
            return f"rule:{c.object_key}"
    return None


def version_text(v: object) -> str:
    """A version column: a number, or a keyword list (the words, cut to `VERSION_CHARS`)."""
    if v is None or (isinstance(v, list) and not v):
        return "none"
    s = ", ".join(map(str, v)) if isinstance(v, list) else f"{v:g}" if isinstance(v, float) else str(v)
    return s if len(s) <= VERSION_CHARS else s[: VERSION_CHARS - 1] + "…"


def _facts(c: Change, status: str | None, gate: str | None) -> gates.Facts:
    extra: dict[str, Any] = {}
    measured = relevance_audit.RelevanceMeasure.from_dict((c.gates.get("replay") or {}).get("relevance"))
    if measured is not None:  # a relevance keyword change: the replay numbers are the re-judged pages
        extra["measure"] = relevance_audit.sentence_part(measured)
    return gates.Facts(c.object_kind, c.object_key, c.from_version, c.to_version,
                       str(c.evidence.get("trigger") or c.reason), status or c.status, gate, extra)  # fmt: skip
