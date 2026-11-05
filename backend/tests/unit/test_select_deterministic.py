"""009 FR-024 (chat 20b5b7f9): the seat count and the boot volume were different in two reports of one chat. The
claims were the same values re-read with new claim ids; the order of the ids decided ties. The same rule must pick
the same value every time, whatever the ids and the order the claims come in."""

import itertools

from automind.domain import evidence as ev


def _claims(attr: str, rows: list[tuple[float, str, str]], ids: list[str]) -> list[ev.ClaimIn]:
    return [ev.ClaimIn(i, attr, v, t, d) for i, (v, t, d) in zip(ids, rows, strict=True)]


SEATS = [(5.0, "SPEC_DATABASE", "km77.com"), (7.0, "SPEC_DATABASE", "auto-data.net")]
BOOT = [(604.0, "PUBLICATION", "autopista.es"), (616.0, "PUBLICATION", "motor.es"), (179.0, "SPEC_DATABASE", "x.es")]


def _every_report(attr: str, rows: list[tuple[float, str, str]]) -> set[tuple[object, ...]]:
    """The selection for every order and every assignment of fresh claim ids (each report re-reads its pages)."""
    out = set()
    for perm in itertools.permutations(rows):
        for ids in itertools.permutations([f"{n:02d}-id" for n in range(len(rows))]):
            s = ev.select_value(attr, _claims(attr, list(perm), list(ids)))
            out.add((s.value, s.confidence_rule, tuple(sorted(map(str, s.alternatives)))))
    return out


def test_seats_tie_picks_the_same_value_every_report():
    got = _every_report("seats", SEATS)
    assert len(got) == 1, got
    assert next(iter(got))[0] == 5.0  # a tie keeps the base configuration (the smaller number)


def test_boot_volume_cluster_value_is_the_same_every_report():
    got = _every_report("boot_volume", BOOT)
    assert len(got) == 1, got
    assert next(iter(got))[0] == 604.0


def test_the_most_supported_value_of_a_cluster_wins_not_the_first_read():
    rows = [(616.0, "PUBLICATION", "a.es"), (604.0, "PUBLICATION", "b.es"), (604.0, "PUBLICATION", "c.es"),
            (616.0, "PUBLICATION", "a.es")]  # fmt: skip
    got = _every_report("boot_volume", rows)
    assert {g[0] for g in got} == {604.0}  # two sites say 604, one site (twice) says 616


def test_two_reselects_on_the_same_claims_give_the_same_value():
    claims = _claims("seats", SEATS, ["b", "a"])
    assert ev.select_value("seats", claims) == ev.select_value("seats", list(reversed(claims)))
