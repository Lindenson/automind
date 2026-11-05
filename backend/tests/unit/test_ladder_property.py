"""Spec 008 US3 / FR-011 / SC-004: no identification state can loop. Seeded random version lists and random replies
(an offered option, "choose for me", nonsense, "remove") drive the pure ladder the way the identify step does:
every scenario ends with one version or a removed car, no level is asked more than the limit, the same question is
never sent twice in a row, and options never contradict a level stated above."""

from __future__ import annotations

import random
from collections import Counter

from automind.domain import ladder
from automind.domain.ladder import Version, Wanted

FUELS = ("petrol", "diesel", "mhev", "hybrid", "phev", "bev")
BOXES = ("manual", "automatic", "dct", "cvt")
DRIVES = ("FWD", "RWD", "AWD")
FAMILY = {"petrol": "TSI", "diesel": "TDI", "mhev": "eTSI", "hybrid": "e:HEV", "phev": "PHEV", "bev": "Electric"}
LIMIT = 2


def _versions(rnd: random.Random) -> list[Version]:
    out = []
    for _ in range(rnd.randint(1, 30)):
        fuel = rnd.choice(FUELS)
        cc = None if fuel == "bev" else rnd.choice((999, 1498, 1968, 2480))
        kw = rnd.randint(50, 250)
        boxes = ("single",) if fuel == "bev" else tuple(rnd.sample(BOXES, rnd.randint(1, 3)))
        drives = tuple(rnd.sample(DRIVES, rnd.randint(1, 2)))
        line = "RS " if rnd.random() < 0.1 else ""
        disp = f"{cc / 1000:.1f} " if cc else ""
        lo = rnd.choice((None, 2015, 2018, 2020))
        hi = None if lo is None or rnd.random() < 0.5 else lo + rnd.randint(1, 6)
        out.append(Version(f"{line}{disp}{FAMILY[fuel]} {round(kw / 0.7355)} CV", fuel, cc, kw, boxes, drives, lo, hi))
    return out


def _stated(rnd: random.Random, vs: list[Version]) -> Wanted:
    v = rnd.choice(vs)
    pick = rnd.random
    return Wanted(
        fuel=v.fuel if pick() < 0.3 else (rnd.choice(FUELS) if pick() < 0.1 else None),
        displacement_l=(
            round(v.engine_cc / 1000, 1) if v.engine_cc and pick() < 0.3 else (2.5 if pick() < 0.1 else None)
        ),
        power_kw=v.power_kw if pick() < 0.2 else (rnd.randint(50, 300) if pick() < 0.1 else None),
        gearbox=rnd.choice(BOXES) if pick() < 0.2 else None,
        drive=rnd.choice(DRIVES) if pick() < 0.15 else None,
        year=rnd.choice((None, 2016, 2021, 2024)),
        words="RS" if pick() < 0.05 else "",
    )


def _run(seed: int) -> tuple[str, Counter[str], int]:
    rnd = random.Random(seed)
    vs = _versions(rnd)
    w = _stated(rnd, vs)
    asks: Counter[str] = Counter()
    chosen = False
    last: tuple[object, ...] | None = None
    for turn in range(40):
        d = ladder.decide(vs, w, asks, limit=LIMIT, chosen=chosen)
        w = d.wanted
        if d.done:
            return "SETTLED", asks, turn
        st = d.step
        assert st.options, f"seed {seed}: a question without options ({st.kind})"
        item = ladder.ITEM[st.kind]
        text = (st.kind, tuple(o.label for o in st.options), asks[item] >= 1)  # the 2nd ask is a rephrase
        assert text != last, f"seed {seed}: the same question twice in a row"
        last = text
        _no_contradiction(seed, vs, w, st)
        asks[item] += 1
        assert asks[item] <= LIMIT, f"seed {seed}: {item} asked {asks[item]} times"
        r = rnd.random()
        if r < 0.05:
            return "REMOVED", asks, turn
        if r < 0.20:
            chosen = True
        elif r < 0.75:
            before = len(ladder.narrow(vs, w).versions)
            w = ladder.apply_option(w, rnd.choice(st.options))
            assert len(ladder.narrow(vs, w).versions) <= before, f"seed {seed}: an option widened the choice"
        # else: nonsense, nothing changes; the ask limit settles the level
    raise AssertionError(f"seed {seed}: no end after 40 turns")


def _no_contradiction(seed: int, vs: list[Version], w: Wanted, st: ladder.Step) -> None:
    """Options never contradict a level stated above that exists for this generation."""
    found = ladder.narrow(vs, w)
    if w.fuel and w.fuel not in found.missing and st.kind in ("ENGINE", "POWER", "FAMILY"):
        for o in st.options:
            assert o.fuel in (w.fuel, None) or (o.fuel == "mhev" and w.fuel in ("petrol", "diesel", "hybrid")), (
                f"seed {seed}: {o.label} offered for fuel {w.fuel}"
            )


def test_no_identification_state_loops() -> None:
    ends: Counter[str] = Counter()
    worst = 0
    for seed in range(1500):
        end, asks, turns = _run(seed)
        ends[end] += 1
        worst = max(worst, turns)
        assert max(asks.values(), default=0) <= LIMIT
    assert ends["SETTLED"] + ends["REMOVED"] == 1500
    assert worst <= len(ladder.ITEMS) * LIMIT + 1  # every level at most `LIMIT` asks


def _ended(v: Version, vs: list[Version], year: int) -> bool:
    end = ladder.sold_until(v, vs)
    return end is not None and end < year


def test_a_year_offers_only_versions_sold_in_it_and_a_new_car_only_versions_on_sale() -> None:
    """009 FR-023: with a year, every option of the first question is a version sold in that year (±1; its own end
    year or the facelift that replaced it) whenever one is; a new car never gets a version that ended."""
    rnd = random.Random(23)
    for _ in range(400):
        vs = _versions(rnd)
        year = rnd.randint(2014, 2027)
        sold = [v for v in vs if ladder.sold_in(v, vs, year)]
        pool = ladder.narrow(vs, Wanted(year=year)).versions
        assert pool and all(v in (sold or vs) for v in pool)
        step = ladder.next_step(ladder.Narrowed(pool), Wanted(year=year))
        assert {o.engine for o in step.options if o.engine} <= {v.engine for v in pool}
        now = ladder.on_sale(vs, year)
        assert now == ([v for v in vs if not _ended(v, vs, year)] or vs)


def test_a_facelift_ends_the_open_ended_version_it_replaced() -> None:
    old = Version("1.6 T-GDi PHEV 265 CV", "phev", 1598, 195, years_from=2020)
    new = Version("1.6 T-GDi PHEV 288 CV", "phev", 1598, 212, years_from=2024)
    diesel = Version("2.2 CRDi 193 CV", "diesel", 2151, 142, years_from=2020)
    other = Version("1.0 TSI 110 CV", "petrol", 999, 81, years_from=2022)
    big = Version("1.5 TSI 150 CV", "petrol", 1498, 110, years_from=2020)
    vs = [old, new, diesel, other, big]
    assert ladder.sold_until(old, vs) == 2023 and ladder.sold_until(new, vs) is None
    assert ladder.sold_until(diesel, vs) is None  # no later diesel: still on sale
    assert ladder.sold_until(big, vs) is None  # a smaller engine added beside it is not its facelift
    assert ladder.on_sale(vs, 2026) == [new, diesel, other, big]
