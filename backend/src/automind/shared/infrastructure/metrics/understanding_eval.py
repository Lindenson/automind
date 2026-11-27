"""The nightly understanding eval as gauges (spec 013 T006).

`scripts/eval_understanding.sh` runs the golden message set on the real model on the host and writes a summary
(`latest.json`, format `EvalSummary`) into `eval-runs/understanding/`, mounted read-only into the app at
`settings().understanding_eval_summary`. The snapshot collector reads it at scrape time (a small local file, no
database: FR-031 holds).

Failures: no file yet → no samples (the stale rule stays silent until the first run). A file that does not parse
→ no samples and one warning in the log; the stale rule then fires after its window, since the timestamp is gone.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

log = logging.getLogger(__name__)

Samples = dict[str, list[tuple[tuple[str, ...], float]]]

GAUGES: dict[str, tuple[str, tuple[str, ...]]] = {
    "understanding_eval_accuracy": ("Nightly understanding eval: share of cases right per field", ("field",)),
    "understanding_eval_ceiling": ("Understanding eval harness ceiling (expected labels) per field", ("field",)),
    "understanding_eval_cases": ("Cases scored by the last understanding eval", ()),
    "understanding_eval_errors": ("Cases of the last understanding eval that failed to run", ()),
    "understanding_eval_cost_eur": ("Model spend of the last understanding eval in euros", ()),
    "understanding_eval_latency_p95_seconds": ("p95 of the understanding step in the last eval", ()),
    "understanding_eval_last_run_timestamp_seconds": ("Unix time the last understanding eval finished", ()),
}


class EvalSummary(BaseModel):
    """The summary the runner writes (`tests/eval/understanding/runner.py --summary`)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    finished_at: float
    model: str
    cases: int
    errors: int
    cost_eur: float
    latency_p95_ms: float
    accuracy: dict[str, float]  # field (and "all") -> share 0..1
    ceiling: dict[str, float]


def samples(path: Path) -> Samples:
    """The gauges of the summary at `path`; {} when there is none or it does not parse (module docstring)."""
    try:
        s = EvalSummary.model_validate_json(path.read_bytes())
    except FileNotFoundError:
        return {}
    except (OSError, ValidationError) as e:
        log.warning("understanding eval summary %s unreadable: %s", path, e)
        return {}
    return {
        "understanding_eval_accuracy": [((f,), v) for f, v in sorted(s.accuracy.items())],
        "understanding_eval_ceiling": [((f,), v) for f, v in sorted(s.ceiling.items())],
        "understanding_eval_cases": [((), float(s.cases))],
        "understanding_eval_errors": [((), float(s.errors))],
        "understanding_eval_cost_eur": [((), s.cost_eur)],
        "understanding_eval_latency_p95_seconds": [((), s.latency_p95_ms / 1000)],
        "understanding_eval_last_run_timestamp_seconds": [((), s.finished_at)],
    }
