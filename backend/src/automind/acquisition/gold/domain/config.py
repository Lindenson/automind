"""`config/gold_datasets.yaml` (with `config/makes.yaml`) typed once: how rows are matched (`MatchCfg`) and the
tolerance and unit of each attribute's gold (`GoldRules`)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from automind.acquisition.domain.tolerance import Tolerance
from automind.shared.contracts.json import JsonObject
from automind.shared.vehicle import specs

MASS_CONVERSION = "eu_running_order_minus_driver"


@dataclass(frozen=True)
class MatchCfg:
    """How dataset rows are matched to a variant (research R3); the defaults are the tested ones."""

    aliases: dict[str, list[str]] = field(default_factory=dict)  # canonical make -> aliases (config/makes.yaml)
    strip_words: tuple[str, ...] = ()
    tolerances: dict[str, Tolerance] = field(default_factory=dict)
    conversions: dict[str, float] = field(default_factory=lambda: {MASS_CONVERSION: -75.0})
    power_kw_tolerance: float = 1.0
    displacement_rel: float = 0.02
    mass_tiebreak_rel: float = 0.03
    min_registrations: int = 2
    default_tolerance: Tolerance = ("rel", 0.03)

    @classmethod
    def from_config(cls, gold: JsonObject, makes: JsonObject | None = None) -> MatchCfg:
        """From `config/gold_datasets.yaml` and `config/makes.yaml`."""
        aliases = {
            str(k): [str(a) for a in (v or {}).get("aliases") or []]
            for k, v in ((makes or {}).get("makes") or {}).items()
        }
        return cls(
            aliases=aliases,
            strip_words=tuple(str(w).lower() for w in gold.get("strip_words") or ()),
            tolerances=tolerances(gold),
            conversions={str(k): float(v) for k, v in (gold.get("conversions") or {MASS_CONVERSION: -75}).items()},
        )

    def tolerance(self, attribute: str) -> Tolerance:
        """The attribute's tolerance, the default one when the config has none."""
        return self.tolerances.get(attribute, self.default_tolerance)


@dataclass(frozen=True)
class GoldRules:
    """The tolerance and unit gold of an attribute is stored with (the reference set and the challenges)."""

    tolerances: Mapping[str, Tolerance]
    units: Mapping[str, str]  # as the datasets publish them; the first dataset naming an attribute wins

    @classmethod
    def from_config(cls, gold: JsonObject) -> GoldRules:
        """From `config/gold_datasets.yaml`."""
        units: dict[str, str] = {}
        for d in (gold.get("datasets") or {}).values():
            units = {**{str(k): str(v) for k, v in (d.get("units") or {}).items()}, **units}
        return cls(tolerances(gold), units)

    def tolerance_of(self, attribute: str) -> Tolerance:
        """(kind, tolerance): the config's, else the attribute's own relative tolerance, else 3 %."""
        if attribute in self.tolerances:
            return self.tolerances[attribute]
        a = specs.ATTRS.get(attribute)
        return ("rel", float(a.tolerance)) if a is not None else ("rel", 0.03)

    def unit_of(self, attribute: str) -> str:
        """The unit: as the datasets publish it, else the canonical one, else empty."""
        a = specs.ATTRS.get(attribute)
        return str(self.units.get(attribute) or (a.unit if a is not None and a.unit else ""))


def tolerances(gold: JsonObject) -> dict[str, Tolerance]:
    """attribute -> ("abs" | "rel", tolerance) of the config's `tolerances`."""
    out: dict[str, Tolerance] = {}
    for attr, t in (gold.get("tolerances") or {}).items():
        kind = "abs" if "abs" in t else "rel"
        out[str(attr)] = (kind, float(t[kind]))
    return out
