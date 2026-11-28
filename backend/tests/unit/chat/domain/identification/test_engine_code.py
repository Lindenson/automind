"""Owner 2026-11-28: an engine code said as a trim word is the engine family the ladder narrows by."""

import pytest

from automind.chat.application.services.identification.stages.narrow_ladder import wanted
from automind.chat.domain.case import CaseCar, Constraints
from automind.chat.domain.identification import ladder


@pytest.mark.parametrize(
    ("text", "code"),
    [("C 200 d", "C 200 d"), ("c200d", "C 200 d"), ("GLC 300 e", "GLC 300 e"), ("A 180", "A 180"),
     ("320d", "320d"), ("320 D", "320d"), ("220д", "220d"), ("M340i", "M340i"), ("118i", "118i"),
     ("M Sport", None), ("Exclusive-Line", None), (None, None), ("320d M Sport", None)],
)  # fmt: skip
def test_engine_codes(text: str | None, code: str | None) -> None:
    assert ladder.engine_code(text) == code


def _v(engine: str, fuel: str = "mhev", kw: int = 120) -> ladder.Version:
    return ladder.Version(engine=engine, fuel=fuel, engine_cc=2000, power_kw=kw)


def test_c_200_d_said_as_a_trim_word_settles_the_engine() -> None:
    """Chat 2026-11-28: "мерседес C 200 d 2026" was asked "C 200 d, C 180, C 220 d …?" again."""
    car = CaseCar(key="car#1", request_text="мерседес C 200 d 2026", make="Mercedes-Benz", model="C-Class",
                  condition="NEW", constraints=Constraints(trim_hint="C 200 d"))  # fmt: skip
    pool = [_v("C 200 d"), _v("C 180", kw=125), _v("C 220 d", kw=145), _v("C 200", kw=150)]
    left = ladder.narrow(pool, wanted(car))
    assert [v.engine for v in left.versions] == ["C 200 d"] and left.missing == []
