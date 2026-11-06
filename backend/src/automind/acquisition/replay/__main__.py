"""`python -m automind.acquisition.replay` (contracts/replay-cli.md).

    python -m automind.acquisition.replay
        (--reader KEY | --reader-spec FILE.json | --extractor KEY [--model MODEL] --allow-llm)
        [--since 30d | --from 2026-10-01 --to 2026-11-05]
        [--domain km77.com] [--attribute max_power ...] [--limit-pages N] [--json] [--mismatches N]

Exit codes: 0 ok · 1 no pages in the period · 2 invalid spec · 3 extractor replay refused · 4 network attempt.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import UTC, datetime, time, timedelta

from automind.acquisition.replay.run import ReplayError, ReplayReport, ReplayRequest, run


def _since(text: str) -> datetime:
    m = re.fullmatch(r"(\d+)\s*([dh])", text.strip())
    if not m:
        raise argparse.ArgumentTypeError("use e.g. 30d or 12h")
    n = int(m.group(1))
    return datetime.now(UTC) - (timedelta(days=n) if m.group(2) == "d" else timedelta(hours=n))


def _day(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m automind.acquisition.replay", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    who = p.add_mutually_exclusive_group(required=True)
    who.add_argument("--reader", help="a stored parser version, e.g. km77@v2")
    who.add_argument("--reader-spec", help="a candidate parser spec (JSON), validated first (exit 2 when invalid)")
    who.add_argument("--extractor", help="an extraction prompt version, e.g. extract_specs@v2 (needs --allow-llm)")
    p.add_argument("--model")
    p.add_argument("--allow-llm", action="store_true")
    p.add_argument("--since", type=_since)
    p.add_argument("--from", dest="from_", type=_day)
    p.add_argument("--to", type=_day)
    p.add_argument("--domain", action="append")
    p.add_argument("--attribute", action="append")
    p.add_argument("--limit-pages", type=int)
    p.add_argument("--json", action="store_true")
    p.add_argument("--mismatches", type=int, default=10)
    return p.parse_args(argv)


def request(a: argparse.Namespace) -> ReplayRequest:
    since = a.since or a.from_
    until = datetime.combine(a.to.date(), time.max, tzinfo=UTC) if a.to else (datetime.now(UTC) if since else None)
    return ReplayRequest(reader=a.reader, reader_spec=a.reader_spec, extractor=a.extractor, model=a.model,
                         since=since, until=until, domains=a.domain, attributes=a.attribute,
                         limit_pages=a.limit_pages, allow_llm=a.allow_llm)  # fmt: skip


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x:.3f}"


def text(r: ReplayReport, n: int) -> str:
    period = f"{r.period['from']} … {r.period['to']}" if r.period else "all stored pages"
    lines = [
        f"{r.version}  ({period})",
        f"  pages {r.pages}  with fields {r.pages_with_fields}  fields/page {r.fields_per_page:.2f}  "
        f"yield {r.yield_:.2f}",
        f"  rows read {r.rows_read}  accepted {r.rows_accepted}  pass rate {_pct(r.pass_rate)}",
        f"  gold covered {r.gold_covered}  match {r.gold_match}  accuracy {_pct(r.accuracy)}  "
        f"lower bound {_pct(r.accuracy_lb)}",
        f"  {r.duration_s:.2f} s  network calls {r.network_calls}  model calls {r.llm_calls}",
    ]
    if r.by_attribute:
        lines.append(
            "  by attribute: " + ", ".join(f"{a} {c['match']}/{c['covered']}" for a, c in r.by_attribute.items())
        )
    for m in r.mismatches[:n]:
        lines.append(f"  ✗ {m['attribute']}: ours {m['ours']} vs gold {m['gold']} {m['unit']} ({m['gold_rule']}, "
                     f"{m['gold_dataset']})  {m['url']}  «{m['quote']}»")  # fmt: skip
    if len(r.mismatches) > n:
        lines.append(f"  … {len(r.mismatches) - n} more mismatches")
    return "\n".join(lines)


async def main_async(argv: list[str] | None = None) -> int:
    a = parse(argv)
    try:
        report = await run(request(a))
    except ReplayError as e:
        print(f"replay: {e}", file=sys.stderr)
        return e.code
    print(json.dumps(report.as_json(), ensure_ascii=False, indent=2) if a.json else text(report, a.mismatches))
    return 0


def main(argv: list[str] | None = None) -> int:
    from automind.shared.infrastructure.config.loader import configure_domain  # noqa: PLC0415

    configure_domain()
    return asyncio.run(main_async(argv))


if __name__ == "__main__":
    raise SystemExit(main())
