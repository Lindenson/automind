"""Spec 013 T006: the nightly eval summary as gauges — read, missing, broken."""

from __future__ import annotations

from pathlib import Path

from automind.shared.infrastructure.metrics.understanding_eval import EvalSummary, samples

SUMMARY = EvalSummary(finished_at=1_800_000_000.0, model="m", cases=148, errors=0, cost_eur=1.15,
                      latency_p95_ms=4567.0, accuracy={"answer": 0.66, "all": 0.2},
                      ceiling={"answer": 0.72, "all": 0.17})  # fmt: skip


def test_summary_becomes_gauges(tmp_path: Path) -> None:
    f = tmp_path / "latest.json"
    f.write_text(SUMMARY.model_dump_json(), encoding="utf-8")
    got = samples(f)
    assert got["understanding_eval_accuracy"] == [(("all",), 0.2), (("answer",), 0.66)]
    assert got["understanding_eval_latency_p95_seconds"] == [((), 4.567)]
    assert got["understanding_eval_last_run_timestamp_seconds"] == [((), 1_800_000_000.0)]


def test_no_file_no_samples(tmp_path: Path) -> None:
    assert samples(tmp_path / "missing.json") == {}


def test_broken_file_no_samples(tmp_path: Path) -> None:
    f = tmp_path / "latest.json"
    f.write_text('{"cases": "many"}', encoding="utf-8")
    assert samples(f) == {}
