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

from automind.acquisition.worker import exporter
from automind.insight.metrics.prom import metric_names

DEPLOY = Path(__file__).resolve().parents[3] / "deploy" / "prometheus"
RULES = DEPLOY / "automind-rules.yml"
NAME = re.compile(r"automind_[a-z0-9_]+")

# contracts/metrics.md, "Shipped rules"
EXPECTED = {
    "AutomindSatisfactionDrop", "AutomindComplaintSpike", "AutomindInaccuracyHigh", "AutomindSourceWrongBurst",
    "AutomindSourceDegraded", "AutomindSourcesBelowMin", "AutomindReaderZero", "AutomindNoDataRise",
    "AutomindFallbackHigh", "AutomindProviderDown", "AutomindBudget80", "AutomindBackgroundBudgetUsed",
    "AutomindLoopStale", "AutomindLoopFailing", "AutomindIssueRegression", "AutomindDown",
    "AutomindWorkerDown",  # spec 011 contracts/task-queue.md
    "AutomindAccuracyDrop", "AutomindSearchesPerValueUp",  # spec 011 US3 (T075)
    "AutomindParserDrift",  # spec 011 US4 (T089)
}  # fmt: skip


def _rules() -> list[dict[str, Any]]:
    doc = yaml.safe_load(RULES.read_text(encoding="utf-8"))
    return [r for g in doc["groups"] for r in g["rules"]]


def test_rules_parse_and_match_the_contract() -> None:
    names = [r["alert"] for r in _rules()]
    assert len(names) == len(set(names)), "duplicate alert names"
    assert set(names) == EXPECTED


def test_every_metric_in_an_expression_is_exported() -> None:
    exported = metric_names() | exporter.metric_names()  # the API and the worker (spec 011)
    unknown = {(r["alert"], m) for r in _rules() for m in NAME.findall(str(r["expr"])) if m not in exported}
    assert not unknown, f"metrics not exported by the API or the worker: {sorted(unknown)}"


def test_worker_metric_families_and_scrape_job() -> None:
    """Spec 011 T056: the worker's families exist, WorkerDown watches its beat, Prometheus scrapes worker:9101."""
    assert {"automind_worker_beat_timestamp_seconds", "automind_acq_tasks", "automind_acq_task_failures_total",
            "automind_acq_task_duration_seconds_bucket"} <= exporter.metric_names()  # fmt: skip
    (down,) = [r for r in _rules() if r["alert"] == "AutomindWorkerDown"]
    assert "automind_worker_beat_timestamp_seconds" in down["expr"] and 'job="automind-worker"' in down["expr"]
    jobs = {j["job_name"]: j for j in yaml.safe_load((DEPLOY / "prometheus.yml").read_text())["scrape_configs"]}
    assert jobs["automind-worker"]["static_configs"][0]["targets"] == ["worker:9101"]
    assert "automind" in jobs  # the API job stays


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


def test_reputation_rules_watch_the_worker_gauges() -> None:
    """Spec 011 T075: accuracy against the baseline and searches per accepted value (SC-006, SC-009)."""
    by = {r["alert"]: r for r in _rules()}
    assert "automind_wrong_share_baseline" in by["AutomindAccuracyDrop"]["expr"]
    assert "1.5" in by["AutomindAccuracyDrop"]["expr"]
    assert "automind_searches_per_accepted_value" in by["AutomindSearchesPerValueUp"]["expr"]
    assert {"automind_searches_per_accepted_value", "automind_wrong_share", "automind_component_acc_lb",
            "automind_wrong_share_baseline"} <= exporter.metric_names()  # fmt: skip
