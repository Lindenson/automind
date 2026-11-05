"""Snapshot codec and retention rules (spec 011 T012, research R1)."""

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from automind.acquisition.snapshots import codec
from automind.acquisition.snapshots.codec import RetentionCfg, SnapshotRow

KM77 = Path(__file__).resolve().parents[1] / "fixtures" / "html" / "km77_bmw_520d_g30.html"
T0 = datetime(2026, 1, 1, tzinfo=UTC)
NOW = datetime(2026, 11, 5, tzinfo=UTC)
CFG = RetentionCfg(plain_days=30, accepted_days=180, max_bytes=10_000)


def test_round_trip_and_hash_of_raw_body():
    raw = KM77.read_bytes()
    body = codec.compress(raw, level=10)
    assert codec.decompress(body) == raw
    assert codec.sha256(raw) == hashlib.sha256(raw).hexdigest()
    assert codec.CODEC == "zstd"


def test_compression_ratio_on_a_spec_page():
    raw = KM77.read_bytes()
    assert len(codec.compress(raw)) / len(raw) < 0.3


def test_retention_class():
    assert codec.retention_class(0, False) == "plain"
    assert codec.retention_class(3, False) == "accepted"
    assert codec.retention_class(0, True) == "pinned"
    assert codec.retention_class(5, True) == "pinned"


def test_keep_until():
    assert codec.keep_until(T0, "plain", CFG) == T0 + timedelta(days=30)
    assert codec.keep_until(T0, "accepted", CFG) == T0 + timedelta(days=180)
    assert codec.keep_until(T0, "pinned", CFG) is None


def test_config_from_yaml_mapping():
    cfg = RetentionCfg.from_config({"max_gb": 5, "keep_days": {"plain": 30, "accepted": 180}, "zstd_level": 10})
    assert cfg.max_bytes == 5 * 1024**3 and cfg.plain_days == 30 and cfg.accepted_days == 180 and cfg.level == 10


def _row(i: str, cls: str, fetched: datetime, size: int, blob: str | None = None) -> SnapshotRow:
    return SnapshotRow(i, fetched, cls, codec.keep_until(fetched, cls, CFG), size, blob or f"blob-{i}")


def test_eviction_deletes_expired_first_even_under_the_cap():
    rows = [_row("old", "plain", NOW - timedelta(days=40), 10), _row("new", "plain", NOW - timedelta(days=1), 10)]
    assert codec.eviction_plan(rows, cap_bytes=10_000, now=NOW) == ["old"]


def test_eviction_over_the_cap_takes_oldest_plain_then_old_accepted_never_pinned():
    rows = [
        _row("pin", "pinned", NOW - timedelta(days=400), 4000),
        _row("acc_old", "accepted", NOW - timedelta(days=200), 3000),  # past 180 days: expired anyway
        _row("acc_new", "accepted", NOW - timedelta(days=10), 3000),
        _row("plain_a", "plain", NOW - timedelta(days=20), 3000),
        _row("plain_b", "plain", NOW - timedelta(days=5), 3000),
    ]
    # 16,000 bytes; cap 9,000: expired accepted goes, then the oldest plain pages until under the cap
    plan = codec.eviction_plan(rows, cap_bytes=9_000, now=NOW)
    assert plan == ["acc_old", "plain_a", "plain_b"]
    assert "pin" not in codec.eviction_plan(rows, cap_bytes=0, now=NOW)
    assert "acc_new" not in codec.eviction_plan(rows, cap_bytes=0, now=NOW)  # accepted < 180 days stays


def test_shared_blob_frees_space_only_when_its_last_snapshot_goes():
    rows = [
        _row("a1", "plain", NOW - timedelta(days=20), 5000, blob="same"),
        _row("a2", "plain", NOW - timedelta(days=10), 5000, blob="same"),
        _row("b", "plain", NOW - timedelta(days=5), 5000),
    ]
    # stored: 10,000 (the shared blob once); cap 6,000 -> a1 frees nothing, a2 frees the shared blob
    assert codec.eviction_plan(rows, cap_bytes=6_000, now=NOW) == ["a1", "a2"]


def test_rows_without_blob_count_nothing():
    rows = [SnapshotRow("meta", NOW - timedelta(days=1), "plain", NOW + timedelta(days=29), 0, None)]
    assert codec.eviction_plan(rows, cap_bytes=0, now=NOW) == []
