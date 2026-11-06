#!/usr/bin/env python3
"""Stored dialogue checkpoints still load with the current code (spec 012 research R4, review B3). Read-only.

    check_checkpoints.py [--database NAME]      # default: the production database `automind` of the compose Postgres

Checks:
1. no checkpoint blob or pending write contains a module path `automind.` (graph state must hold plain data only,
   or a later module move breaks resuming);
2. the latest state of every chat thread loads with the current graph and its pending nodes (`next`, interrupts)
   are nodes the current graph has (node ids are frozen during spec 012).
Run from the repo root with the backend environment: `cd backend && uv run python ../scripts/check_checkpoints.py`.
Exit 1 on any failure.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--database", default="automind")
    a = ap.parse_args(argv)
    return asyncio.run(check(_url(a.database)))


async def check(url: str) -> int:
    import psycopg

    from automind.chat.infrastructure.checkpoint import checkpointer, psycopg_conninfo# noqa: PLC0415 - path may move

    failures: list[str] = []
    async with await psycopg.AsyncConnection.connect(psycopg_conninfo(url)) as conn:
        cur = await conn.execute(
            "select (select count(*) from checkpoint_blobs), "
            "(select count(*) from checkpoint_blobs where position('automind.' in encode(blob, 'escape')) > 0), "
            "(select count(*) from checkpoint_writes where position('automind.' in encode(blob, 'escape')) > 0), "
            "(select count(distinct thread_id) from checkpoints)"
        )
        blobs, blob_paths, write_paths, threads = await cur.fetchone()  # type: ignore[misc]
        threads_rows = await (await conn.execute("select distinct thread_id from checkpoints")).fetchall()
    print(f"blobs {blobs}, with module paths {blob_paths}; pending writes with module paths {write_paths}; "
          f"threads {threads}")  # fmt: skip
    if blob_paths or write_paths:
        failures.append("module paths found in stored state: graph state must be plain data")
    graph_mod = _graph_module()
    async with checkpointer(url, max_size=4) as saver:
        graph = graph_mod.build_graph(saver)
        nodes = set(graph.get_graph().nodes)
        pending = 0
        for (thread_id,) in threads_rows:
            try:
                snap = await graph.aget_state({"configurable": {"thread_id": thread_id}})
            except Exception as e:  # noqa: BLE001 - report every thread that does not load
                failures.append(f"{thread_id}: state does not load: {type(e).__name__}: {e}")
                continue
            unknown = [n for n in snap.next if n not in nodes]
            if unknown:
                failures.append(f"{thread_id}: pending nodes not in the graph: {unknown}")
            pending += bool(snap.next)
    print(f"loaded {len(threads_rows)} threads, {pending} with a pending node")
    for f in failures:
        print("FAIL", f)
    return 1 if failures else 0


def _graph_module():  # noqa: ANN202 - the module moves during spec 012
    import importlib

    for name in ("automind.chat.dialog.graph", "automind.chat.dialog.graph"):
        try:
            return importlib.import_module(name)
        except ImportError:
            continue
    raise SystemExit("graph module not found")


def _url(database: str) -> str:
    env = dict(os.environ)
    dotenv = REPO / ".env.docker"
    if dotenv.exists():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            k, sep, v = line.partition("=")
            if sep and not line.startswith("#"):
                env.setdefault(k.strip(), v.strip().strip('"'))
    pw, port = env.get("POSTGRES_PASSWORD", ""), env.get("AUTOMIND_DB_PORT", "5433")
    return f"postgresql+asyncpg://automind:{pw}@127.0.0.1:{port}/{database}"


if __name__ == "__main__":
    sys.exit(main())
