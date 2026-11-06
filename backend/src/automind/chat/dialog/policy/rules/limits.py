"""Rules before everything else (spec 007): the hop limit, the report after a turn timeout, a panel edit."""

from __future__ import annotations

from automind.chat.dialog.policy.contracts import Situation
from automind.chat.domain.decision import Action
from automind.chat.domain.fingerprint import fingerprint


def hop_limit(s: Situation) -> Action | None:
    """FR-027: a turn that went round too often ends with a partial answer from what it has."""
    if s.hops < s.max_hops:
        return None
    if any(c.variant_id for c in s.case.cars):
        return Action(kind="REPORT", reason="hop limit: a report from the data at hand")
    return Action(kind="ANSWER_GENERAL", reason="hop limit: a plain answer")


def report_after_timeout(s: Situation) -> Action | None:
    """FR-029: after a timeout, the report from the saved data (never research or questions again)."""
    if s.request == "report_saved" and any(c.variant_id for c in s.case.cars):
        return Action(kind="REPORT", reason="turn timeout: report from the saved data")
    return None


def panel_edit(s: Situation) -> Action | None:
    """FR-012, FR-013: a panel edit recomputes from the validated data. It never researches, asks or confirms: when
    it needs new data, the next message decides."""
    if not (s.request == "rescore" and s.case.cars):
        return None
    if s.last_fingerprint is None:
        return Action(kind="REPORT", reason="no report yet: a full report")
    now = fingerprint(s.case)
    if now == s.last_fingerprint:
        return Action(kind="ANSWER_FROM_CONTEXT", nothing_new=True, reason="nothing_new")
    if ":" in s.last_fingerprint and now.split(":")[0] != s.last_fingerprint.split(":")[0]:
        return Action(kind="REPORT", reason="data_changed")  # other cars: a full report on what is cached
    return Action(kind="RESCORE", reason="params_changed")
