"""The report's wording in the person's language (implements `report.contracts.ReportWording`): the phrases of
`phrases` and the verdict, insight, electric and suggestion texts of `report_text`."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from automind.chat.dialog import phrases, report_text
from automind.chat.domain.verdict.insights import InsightSet
from automind.chat.domain.verdict.verdict import Verdict


class DialogWording:
    def t(self, key: str, lang: str | None, **params: object) -> str:
        return phrases.t(key, lang, **params)

    def energy_input(self, name: str, lang: str | None) -> str:
        return phrases.energy_input(name, lang)

    def market_name(self, code: str | None, lang: str | None) -> str:
        return phrases.market_name(code, lang)

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

    def suggestions_block(self, items: list[Any], names: Mapping[str, str],
                          lang: str | None) -> dict[str, Any] | None:  # fmt: skip
        return report_text.suggestions_block(items, names, lang)


WORDING = DialogWording()
