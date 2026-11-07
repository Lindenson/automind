"""Warnings the plan gives about a car (spec 004): sources are scarce for an old car, or the car is not sold new in
Spain. Each is shown once in a turn."""

from __future__ import annotations

from automind.chat.application.services.assessment.contracts import PlanWording
from automind.chat.application.services.report.blocks.notice import Notice, notice
from automind.chat.domain.case import CaseFile
from automind.shared.research_order.plan import ResearchPlan


def new_warnings(plan: ResearchPlan, case: CaseFile, shown: frozenset[str], words: PlanWording) -> list[Notice]:
    """The plan's warnings as notices, without those whose text the turn already shows."""
    out: list[Notice] = []
    for w in plan.warnings:
        car = case.car(w.car_key)
        text = words.plan_warning(w.kind, car.label or car.request_text)
        if text not in shown:
            out.append(notice(text, "warning"))
    return out
