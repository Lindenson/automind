"""The behaviour diff of spec 012 (scripts/refactor/diff_behaviour.py + behaviour_dump_plugin.py)."""

import importlib.util
import json
import sys
from pathlib import Path

_DIR = Path(__file__).resolve().parents[4] / "scripts" / "refactor"


def _load(name: str):  # noqa: ANN202
    spec = importlib.util.spec_from_file_location(name, _DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


plugin = _load("behaviour_dump_plugin")
diff = _load("diff_behaviour")


def test_normalise_ids_in_keys_and_values_hashes_times_and_volatile_keys() -> None:
    events = [
        {
            "chat": "70f7dcef-7605-4341-a3e0-c095d09ce4ad",
            "payload": {
                "scores": {"70f7dcef-7605-4341-a3e0-c095d09ce4ad": 91.0},
                "fingerprint": "47d71ddbed27918e:7c897e18f7db77ef",
                "at": "2026-11-06T12:00:00+00:00",
                "duration_ms": 12,
                "text": "seen 2026-11-06 10:01:02",
                "power": 140,
            },
        }
    ]
    assert plugin.normalise(events) == [
        {
            "chat": "<id0>",
            "payload": {
                "scores": {"<id0>": 91.0},
                "fingerprint": "<id1>:<id2>",
                "at": "<v>",
                "duration_ms": "<v>",
                "text": "seen <ts>",
                "power": 140,
            },
        }
    ]


def _dumps(tmp: Path, name: str, b1: list, b2: list, h: list) -> tuple[Path, Path, Path]:
    dirs = tuple(tmp / d for d in ("b1", "b2", "h"))
    for d, ev in zip(dirs, (b1, b2, h), strict=True):
        d.mkdir(exist_ok=True)
        (d / name).write_text(json.dumps(ev))
    return dirs


E1 = {"type": "status", "payload": {"text": "specs", "opts": ["a", "b"]}}
E2 = {"type": "status", "payload": {"text": "reviews", "opts": ["b", "a"]}}


def test_stable_test_is_compared_strictly_and_a_real_change_is_caught(tmp_path: Path) -> None:
    changed = {"type": "status", "payload": {"text": "specs!", "opts": ["a", "b"]}}
    r = diff.compare(*_dumps(tmp_path, "t.json", [E1, E2], [E1, E2], [E1, changed]))
    assert r["same"] == [] and r["differs"][0].startswith("t.json (event 1")
    r = diff.compare(*_dumps(tmp_path, "t.json", [E1, E2], [E1, E2], [E2, E1]))
    assert r["differs"], "order matters when the base is stable"


def test_unstable_order_is_compared_canonically_and_content_changes_still_fail(tmp_path: Path) -> None:
    r = diff.compare(*_dumps(tmp_path, "t.json", [E1, E2], [E2, E1], [E2, E1]))
    assert r["unstable"] == ["t.json"]
    lost = {"type": "status", "payload": {"text": "reviews", "opts": ["a"]}}
    r = diff.compare(*_dumps(tmp_path, "t.json", [E1, E2], [E2, E1], [E1, lost]))
    assert r["differs"] == ["t.json (as multiset)"]


def test_racy_tests_are_listed_not_gated(tmp_path: Path) -> None:
    other = {"type": "status", "payload": {"text": "paused", "opts": []}}
    r = diff.compare(*_dumps(tmp_path, "t.json", [E1], [other], [E2]))
    assert r["racy"] == ["t.json"] and diff.report(r) == 0
