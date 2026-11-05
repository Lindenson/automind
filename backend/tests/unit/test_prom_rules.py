"""Shipped Prometheus rules (spec 010 T074, FR-032): they parse, name only exported metrics, and carry the labels
and annotations the alert routing and the owner rely on."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from automind.insight.metrics.prom import metric_names

RULES = Path(__file__).resolve().parents[3] / "deploy" / "prometheus" / "automind-rules.yml"
NAME = re.compile(r"automind_[a-z0-9_]+")

# contracts/metrics.md, "Shipped rules"
EXPECTED = {
    "AutomindSatisfactionDrop", "AutomindComplaintSpike", "AutomindInaccuracyHigh", "AutomindSourceWrongBurst",
    "AutomindSourceDegraded", "AutomindSourcesBelowMin", "AutomindReaderZero", "AutomindNoDataRise",
    "AutomindFallbackHigh", "AutomindProviderDown", "AutomindBudget80", "AutomindBackgroundBudgetUsed",
    "AutomindLoopStale", "AutomindLoopFailing", "AutomindIssueRegression", "AutomindDown",
}  # fmt: skip


def _rules() -> list[dict[str, Any]]:
    doc = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    return [r for g in doc["groups"] for r in g["rules"]]


def test_rules_parse_and_match_the_contract() -> None:
    names = [r["alert"] for r in _rules()]
    assert len(names) == len(set(names)), "duplicate alert names"
    assert set(names) == EXPECTED


def test_every_metric_in_an_expression_is_exported() -> None:
    exported = metric_names()
    unknown = {(r["alert"], m) for r in _rules() for m in NAME.findall(str(r["expr"])) if m not in exported}
    assert not unknown, f"metrics not exported by automind.insight.metrics.prom: {sorted(unknown)}"


def test_every_rule_has_severity_summary_and_for() -> None:
    for r in _rules():
        assert r.get("labels", {}).get("severity") in {"warning", "critical"}, r["alert"]
        assert str(r.get("annotations", {}).get("summary", "")).strip(), r["alert"]
        assert str(r.get("annotations", {}).get("admin", "")).startswith("/"), r["alert"]
        assert "for" in r, r["alert"]


@pytest.mark.skipif(shutil.which("promtool") is None, reason="promtool not on PATH")
def test_promtool_check_rules() -> None:
    res = subprocess.run(  # noqa: S603
        [shutil.which("promtool") or "promtool", "check", "rules", str(RULES)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stdout + res.stderr
