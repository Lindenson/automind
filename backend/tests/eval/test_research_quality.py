"""Research quality eval (spec 003 T011), live: runs eval/run_research_eval.py on the benchmark.

SEARCH_PROVIDER=tavily uv run pytest tests/eval/test_research_quality.py -m live -s   # baseline
uv run pytest tests/eval/test_research_quality.py -m live -s                          # new build
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.live
def test_research_quality_eval():
    provider = os.environ.get("SEARCH_PROVIDER")
    label = "baseline" if provider == "tavily" else "v2"
    cmd = [sys.executable, str(ROOT / "eval" / "run_research_eval.py"), "--label", label]
    if provider:
        cmd += ["--provider", provider]
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}  # the script derives its own DB
    subprocess.run(cmd, check=True, env=env, cwd=ROOT)
