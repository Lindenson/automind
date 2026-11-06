"""Worker settings from config/acquisition.yaml (`worker`, `schedule`, `prefetch`, `tasks`).

The YAML file is the only source of these values (spec 012 FR-019): a missing file or section fails at start.
"""

from __future__ import annotations

import copy
from typing import Any

from automind.infrastructure.config import load_yaml

SECTIONS = ("worker", "schedule", "prefetch", "tasks")


def worker_config() -> dict[str, Any]:
    """A fresh (mutable) copy each call."""
    data = load_yaml("acquisition.yaml")
    missing = [k for k in SECTIONS if data.get(k) is None]
    if missing:
        raise KeyError(f"config/acquisition.yaml lacks {missing}")
    return {k: copy.deepcopy(data[k]) for k in SECTIONS}
