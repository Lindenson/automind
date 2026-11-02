"""Research quality eval (spec 003 T011; SC-001..SC-006, SC-010).

Runs a new Standard research (round 0 + one gap round for areas below their minimum) for every car in
eval/research_benchmark.yaml, in a fresh database, and writes eval/out/<label>-<date>.{json,md}.

    uv run python eval/run_research_eval.py --provider tavily --label baseline     # 002 search path
    uv run python eval/run_research_eval.py --label v2                              # default provider
    uv run python eval/run_research_eval.py --cars 3 --label smoke                  # first 3 cars only

Live: calls real models and web search (costs money). The database `automind_eval_<label>` is dropped
and recreated, so every run starts from an empty catalog and cache.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

ROOT = Path(__file__).resolve().parent
AREAS = ["specs", "measured", "price", "maintenance", "reliability", "reviews"]


def _db_urls(label: str) -> tuple[str, str]:
    base = os.environ.get("DATABASE_URL") or ""
    if not base:
        from automind.config import settings  # noqa: PLC0415

        base = settings().database_url
    parts = urlsplit(base)
    name = f"automind_eval_{label}"
    url = base.replace(f"{parts.path}", f"/{name}", 1)
    admin = base.replace(f"{parts.path}", "/postgres", 1)
    return url, admin


async def _recreate_db(admin_url: str, name: str) -> None:
    from sqlalchemy import text  # noqa: PLC0415
    from sqlalchemy.ext.asyncio import create_async_engine  # noqa: PLC0415

    eng = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with eng.connect() as c:
        await c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await c.execute(text(f'CREATE DATABASE "{name}"'))
    await eng.dispose()


async def run(args: argparse.Namespace) -> dict[str, Any]:
    from sqlalchemy import func, select  # noqa: PLC0415

    from automind.application import research as rs  # noqa: PLC0415
    from automind.application import resolve  # noqa: PLC0415
    from automind.application.usage import Limits, TurnBudget, current_budget  # noqa: PLC0415
    from automind.infrastructure import db  # noqa: PLC0415
    from automind.infrastructure.adapters import live_ports  # noqa: PLC0415
    from automind.infrastructure.config import configure_domain  # noqa: PLC0415
    from automind.infrastructure.db.repositories import EventRepo, JobRepo  # noqa: PLC0415
    from automind.infrastructure.events import EventBus  # noqa: PLC0415
    from automind.infrastructure.llm_gateway import prices  # noqa: PLC0415
    from automind.orchestration.prompts import load_all  # noqa: PLC0415

    configure_domain()
    await db.init_db()
    ports = live_ports(EventBus(EventRepo()), load_all())
    jobs = JobRepo()
    bench = yaml.safe_load((ROOT / "research_benchmark.yaml").read_text(encoding="utf-8"))["cars"]
    if args.cars:
        bench = bench[: args.cars]
    chat_id = f"eval-{args.label}"
    out_cars = []

    async def emit(stage: str, text: str) -> None:
        if args.verbose:
            print(f"    [{stage}] {text}")

    for car in bench:
        gens = {g: (a, b) for g, a, b in ports.ref.generations.get(f"{car['make']}|{car['model']}", [])}
        y_from, y_to = gens.get(car["generation"], (car["years"][0], None))
        ident = resolve.VariantIdentity(
            make=car["make"], model=car["model"], generation=car["generation"], generation_years_from=y_from,
            generation_years_to=y_to, variant_name=car["variant"], powertrain=car["powertrain"],
            body_class=car.get("body"), vehicle_class=car.get("class"), certainty="exact",
        )  # fmt: skip
        v = await resolve.upsert_variant(ident, ports.ref)
        turn_id = str(uuid.uuid4())
        budget = TurnBudget(chat_id=chat_id, turn_id=turn_id, prices=prices(), limits=Limits(max_llm_calls=400,
                            hard_cap_eur=args.cap_per_car))  # fmt: skip
        token = current_budget.set(budget)
        started = time.monotonic()
        areas: dict[str, Any] = {}
        try:
            for round_ in (0, 1):
                todo = [a for a in AREAS if round_ == 0 or not areas[a]["minimum_met"]]
                sem = asyncio.Semaphore(4)

                async def one(area: str, r: int = round_, sem=sem, turn_id=turn_id, v=v) -> tuple[str, Any]:  # noqa: ANN001
                    async with sem:
                        row = await jobs.create(chat_id, turn_id, v.id, area, r)
                        res = await rs.run_job(ports, rs.JobSpec(row.id, v.id, area, r), emit)
                        await jobs.mark(row.id, "DONE" if res.ok else "FAILED", error=res.error)
                        return area, res

                for area, res in await asyncio.gather(*(one(a) for a in todo)):
                    prev = areas.get(area, {"docs": 0, "accepted": 0, "rejected": 0, "errors": []})
                    areas[area] = {
                        "minimum_met": bool(res.minimum_met),
                        "docs": prev["docs"] + res.docs,
                        "accepted": prev["accepted"] + res.accepted,
                        "rejected": prev["rejected"] + res.rejected,
                        "errors": prev["errors"] + ([res.error] if res.error else []),
                        "rounds": round_ + 1,
                    }
        finally:
            current_budget.reset(token)
        duration = time.monotonic() - started
        async with db.sessionmaker()() as s:
            power = (
                await s.execute(
                    select(db.SpecValue.value_num).where(
                        db.SpecValue.variant_id == v.id, db.SpecValue.attribute == "max_power", db.SpecValue.available
                    )
                )
            ).scalar_one_or_none()
            search_cost = (
                await s.execute(select(func.coalesce(func.sum(db.SearchCall.cost_eur), 0)).where(
                    db.SearchCall.turn_id == turn_id))
            ).scalar_one()  # fmt: skip
            llm_cost = (
                await s.execute(select(func.coalesce(func.sum(db.LLMCall.cost_eur), 0)).where(
                    db.LLMCall.turn_id == turn_id))
            ).scalar_one()  # fmt: skip
            searches = (await s.execute(select(func.count()).where(db.SearchCall.turn_id == turn_id))).scalar_one()
        wrong = None
        if power is not None and car.get("power_ps"):
            expected_kw = car["power_ps"] * 0.7355
            wrong = abs(power - expected_kw) / expected_kw > 0.06
        accepted = sum(a["accepted"] for a in areas.values())
        rec = {
            "car": f"{car['make']} {car['model']} {car['generation']} {car['variant']}",
            "trap": car.get("trap", False),
            "areas": areas,
            "minimum_met_share": sum(a["minimum_met"] for a in areas.values()) / len(AREAS),
            "accepted_values": accepted,
            "rejected_values": sum(a["rejected"] for a in areas.values()),
            "search_calls": int(searches),
            "search_cost_eur": float(search_cost),
            "llm_cost_eur": float(llm_cost),
            "cost_per_accepted_eur": (float(search_cost) + float(llm_cost)) / accepted if accepted else None,
            "max_power_kw": power,
            "wrong_variant_power": wrong,
            "duration_s": round(duration, 1),
        }
        out_cars.append(rec)
        print(
            f"{rec['car']}: minimum met {rec['minimum_met_share']:.0%}, accepted {accepted}, "
            f"search €{rec['search_cost_eur']:.3f}, llm €{rec['llm_cost_eur']:.3f}, {rec['duration_s']} s",
            flush=True,
        )

    return summarize(args, out_cars)


def summarize(args: argparse.Namespace, cars: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(cars)
    per_area = {a: sum(c["areas"][a]["minimum_met"] for c in cars) / n for a in AREAS}
    search = sum(c["search_cost_eur"] for c in cars)
    llm = sum(c["llm_cost_eur"] for c in cars)
    accepted = sum(c["accepted_values"] for c in cars)
    durations = sorted(c["duration_s"] for c in cars)
    return {
        "label": args.label,
        "provider": os.environ.get("SEARCH_PROVIDER") or "config default",
        "date": datetime.now(UTC).isoformat(timespec="seconds"),
        "cars": n,
        "minimum_met_share": sum(c["minimum_met_share"] for c in cars) / n,
        "minimum_met_by_area": per_area,
        "search_cost_eur": round(search, 4),
        "llm_cost_eur": round(llm, 4),
        "search_cost_per_2_cars_eur": round(2 * search / n, 4),
        "cost_per_accepted_value_eur": round((search + llm) / accepted, 5) if accepted else None,
        "accepted_values": accepted,
        "wrong_variant_power": sum(1 for c in cars if c["wrong_variant_power"]),
        "power_checked": sum(1 for c in cars if c["wrong_variant_power"] is not None),
        "duration_p90_s": durations[min(n - 1, int(0.9 * n))],
        "per_car": cars,
    }


def write(result: dict[str, Any]) -> Path:
    out = ROOT / "out"
    out.mkdir(exist_ok=True)
    stem = f"{result['label']}-{result['date'][:10]}"
    (out / f"{stem}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [
        f"# Research eval: {result['label']} ({result['provider']}, {result['date']})",
        "",
        f"- cars: {result['cars']}",
        f"- areas meeting their minimum: {result['minimum_met_share']:.0%}",
        "  - " + ", ".join(f"{a} {s:.0%}" for a, s in result["minimum_met_by_area"].items()),
        f"- search cost: €{result['search_cost_eur']:.3f} (per 2 cars €{result['search_cost_per_2_cars_eur']:.3f})",
        f"- LLM cost: €{result['llm_cost_eur']:.3f}",
        f"- accepted values: {result['accepted_values']}",
        f"- cost per accepted value: €{result['cost_per_accepted_value_eur']}",
        f"- wrong-variant power values: {result['wrong_variant_power']} of {result['power_checked']} checked",
        f"- research duration per car p90: {result['duration_p90_s']} s",
        "",
        "| Car | Min. met | Accepted | Search € | LLM € | s |",
        "|---|---|---|---|---|---|",
        *(
            f"| {c['car']} | {c['minimum_met_share']:.0%} | {c['accepted_values']} | {c['search_cost_eur']:.3f} | "
            f"{c['llm_cost_eur']:.3f} | {c['duration_s']} |"
            for c in result["per_car"]
        ),
    ]
    (out / f"{stem}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out / f"{stem}.md"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--provider", help="search provider override (SEARCH_PROVIDER)")
    ap.add_argument("--cars", type=int, default=0, help="only the first N benchmark cars")
    ap.add_argument("--cap-per-car", type=float, default=2.0, help="cost cap per car (EUR)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    if args.provider:
        os.environ["SEARCH_PROVIDER"] = args.provider
    url, admin = _db_urls(args.label)
    asyncio.run(_recreate_db(admin, f"automind_eval_{args.label}"))
    os.environ["DATABASE_URL"] = url
    sys.path.insert(0, str(ROOT.parent / "src"))
    from automind.config import settings  # noqa: PLC0415

    settings.cache_clear()  # _db_urls may have read the default URL: drop it so the eval DB is used
    assert settings().database_url == url, "eval must run on its own database"
    result = asyncio.run(run(args))
    print(f"\nwritten: {write(result)}")


if __name__ == "__main__":
    main()
