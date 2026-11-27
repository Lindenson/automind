"""Spec 016 T308: the §1 table of the narration spec and the extra probes of its coverage audit (§B), run against the
real guard with the facts as `writer_summary` shapes them (Sorento 42 500 €, 6.6 l, 169 kW, costlier over the period;
Prado 38 900 €, 9.8 l, 150 kW; reliability a tie; verdict a tie). Each row: what the number check leaves and which
rules fire. Ratios and percentages ("в 1,5 раза", "на 9 %") stay removed until N2's grammar computes them."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from automind.chat.application.services.report.contracts import CheckInput
from automind.chat.dialog.guard import TOPIC_WORDS, check_numbers, numbers_in, report_violations, sentences
from automind.chat.dialog.report_text import reason_text
from automind.chat.domain.verdict import insights as ins

CONFIG = Path(__file__).resolve().parents[4] / "config" / "insights.yaml"


S, P = "v-sorento", "v-prado"
NAMES = {S: "Kia Sorento", P: "Toyota Land Cruiser Prado"}

rules = ins.rules_from_config(yaml.safe_load(CONFIG.read_text()))
cars = [
    ins.CarValues(
        S,
        NAMES[S],
        {
            "official_price_es": 42500,
            "consumption": 6.6,
            "max_power": 169,
            "tco_period": 31800,
            "tco_per_year": 3100,
            "reliability_score": 70,
        },
        energy_eur_per_unit=1.6,
    ),
    ins.CarValues(
        P,
        NAMES[P],
        {
            "official_price_es": 38900,
            "consumption": 9.8,
            "max_power": 150,
            "tco_period": 30600,
            "tco_per_year": 3550,
            "reliability_score": 72,
        },
        energy_eur_per_unit=1.5,
    ),
]
iset = ins.build(cars, ins.Profile(weights={"purchase_price": 1, "efficiency": 1}, years=5), rules)

# The writer's facts as `writer_summary` shapes them (specs as `display` writes them, the ownership cost as
# `ownership_facts`, the insights as `insights_for_llm` -> `reason_text`), and the case summary with the year.
facts = {
    "cars": [
        {
            "label": "Kia Sorento 1.6 T-GDi HEV",
            "specs": {
                "official_price_es": {"value": "42.500 €"},
                "consumption": {"value": "6.6"},
                "max_power": {"value": "169 kW (230 PS)"},
            },
        },
        {
            "label": "Toyota Land Cruiser Prado 2.8 D-4D",
            "specs": {
                "official_price_es": {"value": "38.900 €"},
                "consumption": {"value": "9.8"},
                "max_power": {"value": "150 kW (204 PS)"},
            },
        },
    ],
    "ownership_cost": {
        "period_years": 5,
        "cars": [
            {
                "car": "Kia Sorento",
                "running_costs_per_year_without_depreciation_eur": 3100,
                "total_over_the_period_including_depreciation_eur": 31800,
            },
            {
                "car": "Toyota Land Cruiser Prado",
                "running_costs_per_year_without_depreciation_eur": 3550,
                "total_over_the_period_including_depreciation_eur": 30600,
            },
        ],
        "cheaper_to_own_over_the_period": "Toyota Land Cruiser Prado",
        "costlier_to_own_over_the_period": ["Kia Sorento"],
        "difference_over_the_period_eur": 1200,
    },
    "insights": {
        "meaningful_differences": [reason_text(i, NAMES, "ru") for i in iset.meaningful()],
        "about_the_same": list(iset.ties),
    },
}
case_summary = "persona UNKNOWN; car#1: Kia Sorento [used, ~2021]; car#2: Toyota Land Cruiser Prado [new]"
blocks: list[dict[str, object]] = []  # the UI blocks add more numbers in production; none needed here

allowed_real = numbers_in(facts) | numbers_in(blocks) | numbers_in(case_summary)

ci = CheckInput(
    has_data=frozenset({"tco", "price", "consumption"} | {i.attribute for i in iset.insights}),
    ties=frozenset(iset.ties),
    tie=True,
    car_names=tuple(sorted(NAMES.values())),
    costlier=("Kia Sorento",),
)


# (text, what the number check leaves, the rules that fire); "" = the whole sentence removed
ROWS = [
    ("2. Prado — 205 л.с.", "", []),  # 204 in the data: was kept (tolerance)
    ("Sorento обходится на 400 € в год дешевле.", "", ["saving_costlier"]),  # 400 was in ALWAYS_OK
    ("Sorento стоит 2021 евро в месяц.", "Sorento стоит 2021 евро в месяц.", []),  # the year: N2 (labelled facts)
    ("Расход у Sorento около двенадцати литров.", "Расход у Sorento около двенадцати литров.", []),  # words: N2
    ("Разница в цене — 3 600 €.", "Разница в цене — 3 600 €.", []),
    ("О надёжности Prado мы знаем мало.", "О надёжности Prado мы знаем мало.", []),  # meaning: N4's judge
    ("Обе хороши, но я бы взял Prado.", "Обе хороши, но я бы взял Prado.", []),  # meaning: N4's judge
    ("Sorento экономичнее в обслуживании.", "Sorento экономичнее в обслуживании.", ["saving_costlier"]),
    ("О надёжности Prado нет данных.", "О надёжности Prado нет данных.", ["absence"]),  # was missed
    (
        "Kia Sorento и Toyota Land Cruiser Prado равны, но я рекомендую Toyota Land Cruiser Prado.",
        "Kia Sorento и Toyota Land Cruiser Prado равны, но я рекомендую Toyota Land Cruiser Prado.",
        ["tie_winner"],
    ),
    ("Обе хороши, но лучший выбор — Prado.", "Обе хороши, но лучший выбор — Prado.", ["tie_winner"]),  # was missed
    ("По надёжности Prado лучше.", "По надёжности Prado лучше.", ["sub_threshold"]),  # was missed
    ("Prado — 204 л.с. и 9,8 л. Расход у Sorento 6,6 л на 100 км, у Prado 9,9 л.", "Prado — 204 л.с. и 9,8 л.", []),
    ("Разница в стоимости владения — 1 200 €, это 4 %.", "", []),  # 4 came from "D-4D" and "€3.550"
    ("Sorento расходует в 1,5 раза меньше.", "", []),  # a ratio: N2
    ("Prado — 204 л.с. и 9,9 л на 100 км, это много.", "", []),  # was cut to the fragment "Prado — 204 л.с."
    (
        "Sorento обходится на 450 € в год дешевле без учёта потери стоимости.",
        "Sorento обходится на 450 € в год дешевле без учёта потери стоимости.",
        [],
    ),
    ("Цена Prado 38 900 €, это на 9 % меньше.", "", []),  # a percentage: N2
    ("Разгон 0–100 км/ч у Prado медленнее.", "Разгон 0–100 км/ч у Prado медленнее.", []),  # a metric name
    ("Расход 9,8 л/100 км.", "Расход 9,8 л/100 км.", []),
]


@pytest.mark.parametrize(("text", "left", "rules"), ROWS, ids=[r[0][:40] for r in ROWS])
def test_the_table(text: str, left: str, rules: list[str]) -> None:
    assert check_numbers(text, allowed_real, cars=2)[0] == left
    assert [v.rule for v in report_violations(text, ci)] == rules


@pytest.mark.parametrize(("written", "fact", "same"), [
    ("9,8", 9.75, True), ("42 500", 42480, True), ("3 600", 3600, True), ("205", 204, False), ("10", 6.7, False),
    ("42 500", 42380, False), ("6,6", 6.58, True), ("20k", 20400, True),
])  # fmt: skip
def test_equal_at_the_written_precision(written: str, fact: float, same: bool) -> None:
    text = f"Значение {written}."
    assert (check_numbers(text, {fact})[1] == 0) is same


def test_one_sentence_splitter_keeps_abbreviations() -> None:
    assert sentences("Prado — 204 л.с. и 9,9 л на 100 км. Sorento — 6,6 л.") == [
        "Prado — 204 л.с. и 9,9 л на 100 км.", "Sorento — 6,6 л."]  # fmt: skip
    assert sentences("Built in 2021 г. in Japan, e.g. Prado. Next.") == [
        "Built in 2021 г. in Japan, e.g. Prado.",
        "Next.",
    ]


def test_every_insight_attribute_has_its_topic_words() -> None:
    attributes = set(yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["attributes"])
    assert attributes <= set(TOPIC_WORDS), sorted(attributes - set(TOPIC_WORDS))


def test_an_engine_code_puts_no_figure_in_the_facts_a_generation_code_does() -> None:
    assert 4.0 not in numbers_in("Toyota Land Cruiser Prado 2.8 D-4D")
    assert 150.0 in numbers_in("Land Cruiser Prado (J150)")  # the text may write "Prado 150"
    assert check_numbers("The Prado J150 is tougher.", set())[1] == 0  # a code in the text is a name
    assert 3550.0 in numbers_in("€3.550") and 3.55 not in numbers_in("€3.550") and 3.55 in numbers_in("3.550 l")
