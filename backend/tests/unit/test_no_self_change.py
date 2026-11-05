"""Spec 010 FR-010, constitution XII: the insight and registry packages have no write path to files
(code, prompts, parsers, configuration). They write only their own database tables."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[2] / "src" / "automind"
PATTERNS = (
    re.compile(r"open\([^)]*['\"][wax]\+?['\"]"),
    re.compile(r"\.write_text\(|\.write_bytes\("),
    re.compile(r"yaml\.(safe_)?dump\([^)]*,\s*\w"),
    re.compile(r"shutil\.(copy|move)|os\.(remove|rename|replace)\("),
    re.compile(r"subprocess|os\.system\("),
)


def test_no_file_writes_in_self_observing_packages():
    hits = []
    for pkg in ("insight", "acquisition"):
        for f in (ROOT / pkg).rglob("*.py"):
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if any(p.search(line) for p in PATTERNS):
                    hits.append(f"{f.relative_to(ROOT)}:{n}: {line.strip()}")
    assert not hits, "self-observing code must not write files:\n" + "\n".join(hits)
