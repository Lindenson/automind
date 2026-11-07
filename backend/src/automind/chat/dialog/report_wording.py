"""The application's wording in the person's language (implements `report.contracts.ReportWording`,
`research.contracts.ResearchWording`, `interpretation.contracts.ReplyWords` and
`assessment.contracts.PlanWording`): the phrases of `phrases`, how a
short reply reads, and the verdict, insight, electric, suggestion and area texts of `report_text`."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from automind.chat.dialog import phrases, report_text
from automind.chat.domain.verdict.insights import InsightSet
from automind.chat.domain.verdict.verdict import Verdict

_PLAN_WARNINGS = {  # the research plan's warnings about a car; English in every chat so far (not in PHRASES yet)
    "OLD_CAR": "{label}: older than 25 years — sources are scarce, several sections may show insufficient data.",
    "NOT_SOLD_IN_ES": "{label}: not sold new in Spain — prices and specifications may refer to another market.",
}


class DialogWording:
    def plan_warning(self, kind: str, label: str) -> str:
        return _PLAN_WARNINGS[kind].format(label=label)

    def t(self, key: str, lang: str | None, **params: object) -> str:
        return phrases.t(key, lang, **params)

    def energy_input(self, name: str, lang: str | None) -> str:
        return phrases.energy_input(name, lang)

    def market_name(self, code: str | None, lang: str | None) -> str:
        return phrases.market_name(code, lang)

    def area_label(self, area: str, lang: str | None) -> str:
        return report_text.area_label(area, lang)

    def thousands(self, value: float, lang: str | None) -> str:
        return report_text.thousands(value, lang)

    def verdict_block(self, v: Verdict, s: InsightSet, names: Mapping[str, str], lang: str | None,
                      years: int | None = None) -> dict[str, Any]:  # fmt: skip
        return report_text.verdict_block(v, s, names, lang, years)

    def profile_lines(self, v: Verdict, names: Mapping[str, str], lang: str | None,
                      years: int | None = None) -> list[str]:  # fmt: skip
        return report_text.profile_lines(v, names, lang, years)

    def insights_for_llm(self, s: InsightSet, v: Verdict, names: Mapping[str, str], lang: str | None,
                         years: int | None = None) -> dict[str, Any]:  # fmt: skip
        return report_text.insights_for_llm(s, v, names, lang, years)

    def electric_lines(self, block: Mapping[str, Any] | None, break_even: Mapping[str, Any] | None,
                       names: Mapping[str, str], lang: str | None, *,
                       years_said: bool = False) -> list[str]:  # fmt: skip
        return report_text.electric_lines(block, break_even, names, lang, years_said=years_said)

    @property
    def gearbox_words(self) -> Mapping[str, str]:
        return phrases.GEARBOX_WORDS

    def choose_for_me(self, text: str | None) -> bool:
        return phrases.choose_for_me(text)

    def go_ahead(self, text: str | None) -> bool:
        return phrases.go_ahead(text)

    def yes_or_no(self, text: str | None) -> str | None:
        return phrases.yes_or_no(text)

    def guess_language(self, texts: list[str]) -> str:
        return phrases.guess_language(texts)

    def stable_language(self, detected: str | None, current: str, earlier: list[str]) -> str | None:
        return phrases.stable_language(detected, current, earlier)

    def suggestions_block(self, items: list[Any], names: Mapping[str, str],
                          lang: str | None) -> dict[str, Any] | None:  # fmt: skip
        return report_text.suggestions_block(items, names, lang)


WORDING = DialogWording()
