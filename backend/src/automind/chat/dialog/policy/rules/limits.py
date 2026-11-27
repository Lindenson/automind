"""Stage LIMITS (spec 007): rules before everything else — the pass limit, the report after a turn timeout, a panel
edit."""

from __future__ import annotations

from typing import ClassVar

from automind.chat.dialog.policy.contracts import RuleOutcome, Situation, Stage, fire, skip
from automind.chat.domain.decision import Action, PolicyConfig
from automind.chat.domain.fingerprint import fingerprint


class PassLimit:
    """A turn that went round too often ends with what it has: a report when a car has a version, else a plain
    answer. Fires on the limit pass, `max_passes + 1`."""

    name: ClassVar[str] = "pass_limit"
    stage: ClassVar[Stage] = Stage.LIMITS
    requirement: ClassVar[str | None] = "spec 007 FR-027"

    def check(self, s: Situation, cfg: PolicyConfig) -> RuleOutcome:
        if s.pass_no <= cfg.max_passes:
            return skip(self, "passes left")
        if any(c.variant_id for c in s.case.cars):
            return fire(self, Action.report("hop limit: a report from the data at hand"))
        return fire(self, Action.answer_general("hop limit: a plain answer"))


class ReportAfterTimeout:
    """After a turn timeout, the report from the saved data — never research or questions again."""

    name: ClassVar[str] = "report_after_timeout"
    stage: ClassVar[Stage] = Stage.LIMITS
    requirement: ClassVar[str | None] = "spec 007 FR-029"

    def check(self, s: Situation, cfg: PolicyConfig) -> RuleOutcome:
        if s.request != "report_saved":
            return skip(self, "not a report after a timeout")
        if not any(c.variant_id for c in s.case.cars):
            return skip(self, "no car has a version")
        return fire(self, Action.report("turn timeout: report from the saved data"))


class PanelEdit:
    """A panel edit recomputes from the validated data. It never researches, asks or confirms: when it needs new
    data, the next message decides."""

    name: ClassVar[str] = "panel_edit"
    stage: ClassVar[Stage] = Stage.LIMITS
    requirement: ClassVar[str | None] = "spec 007 FR-012, FR-013"

    def check(self, s: Situation, cfg: PolicyConfig) -> RuleOutcome:
        if s.request != "rescore":
            return skip(self, "not a panel edit")
        if not s.case.cars:
            return skip(self, "no cars in the case")
        if s.last_fingerprint is None:
            return fire(self, Action.report("no report yet: a full report"))
        now = fingerprint(s.case)
        if now == s.last_fingerprint:
            return fire(self, Action.answer_from_context("nothing_new", nothing_new=True))
        if ":" in s.last_fingerprint and now.split(":")[0] != s.last_fingerprint.split(":")[0]:
            return fire(self, Action.report("data_changed"))  # other cars: a full report on what is cached
        return fire(self, Action.rescore("params_changed"))
