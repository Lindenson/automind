"""Vector blame: which component made a wrong value wrong (spec 011 FR-011, research R9). Pure.

Rules in order, the first that matches decides (share 1.0 unless stated):

1. `fusion`       the claim itself matches the truth but the selected value does not → merging chose wrong
2. `relevance`    the page's verdict was UNCERTAIN / MULTI_VARIANT, or the claimed value is the gold of a sibling
                  variant → the page was about another car; if the truth is also on the page, 0.5 relevance and
                  0.5 our reading (parser or extractor)
3. `units_sense`  the claimed number, read in another unit known to the unit layer (PS↔kW, kgf·m↔N·m, …), is the
                  truth; or a hybrid's engine-only power/torque was taken for the system figure (sense rule)
4. `parser` / `extractor`  the truth (in any accepted unit) is in the excerpt or the stored page → our reading by
                  its producer (reader version, or prompt version + model); only on the raw page and not in the
                  excerpt, or a MEDIUM-confidence truth → disputed (a judge must confirm, R9)
5. `source`       otherwise: the page states the wrong number

Only components with a share > 0 have their reputation changed (`component_keys`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

COMPONENTS = ("source", "relevance", "parser", "extractor", "units_sense", "fusion")
# the single labels of spec 010 (truth_signals.blame)
LABEL_010 = {"source": "source", "relevance": "relevance", "parser": "parser", "extractor": "extractor",
             "units_sense": "check", "fusion": "fusion"}  # fmt: skip
# component -> component_reputation.kind (data-model 0021); the source share goes to `capabilities`
REPUTATION_KIND = {"parser": "parser", "extractor": "extractor", "relevance": "relevance", "units_sense": "rule",
                   "fusion": "fusion"}  # fmt: skip
FUSION_KEY = "merge@1"
VAGUE_RELEVANCE = ("UNCERTAIN", "MULTI_VARIANT")
# number in another unit × factor = canonical value, per attribute (the unit layer's conversions)
UNIT_RULES: dict[str, dict[str, float]] = {
    "max_power": {"units.ps_kw": 0.73549875, "units.hp_kw": 0.745699872},
    "max_torque": {"units.kgfm_nm": 9.80665, "units.lbft_nm": 1.35581795},
    "curb_mass": {"units.lb_kg": 0.45359237},
    "range_wltp": {"units.mi_km": 1.609344},
    "top_speed": {"units.mph_kmh": 1.609344},
}
ENGINE_WORDS = ("motor térmico", "motor termico", "motor de combustión", "motor de combustion", "thermique",
                "verbrennungsmotor", "combustion engine", "engine only", "petrol engine", "motor gasolina",
                "motore termico", "ice ")  # fmt: skip
TIGHT = 0.005  # "the truth occurs": a number within 0.5 % (or 0.5 units)

_NUM = re.compile(r"\d+(?:[.,]\d+)*")


@dataclass(frozen=True)
class BlameCase:
    attribute: str | None
    claim_value: float | None
    truth: float | None  # canonical unit; None when only the checks know it is wrong (physics)
    tolerance: tuple[str, float] = ("rel", 0.02)
    selected_value: float | None = None
    producer: str = "extractor"  # reader | extractor | dataset | user
    producer_version: str | None = None
    model: str | None = None
    relevance: str | None = None  # page_relevance verdict for the claim's page and variant
    relevance_version: str | None = None
    siblings: tuple[float, ...] = ()  # gold of sibling variants (same model, other engine/trim)
    excerpt: str = ""
    page_text: str = ""  # the stored page (snapshot or cached text)
    truth_confidence: str = "HIGH"
    hybrid: bool = False
    domain: str = ""
    truth_alternatives: tuple[float, ...] = ()  # other readings of the truth (010 wrapper: "1.598")


@dataclass(frozen=True)
class Blame:
    vector: dict[str, float]
    rule: str  # fusion | relevance | units_sense | parser | extractor | source | not_wrong
    disputed: bool = False
    rule_id: str | None = None  # units/sense rule

    def top(self) -> str:
        if not self.vector:
            return "source"
        return max(COMPONENTS, key=lambda c: (self.vector.get(c, 0.0), -COMPONENTS.index(c)))


def numbers(text: str) -> set[float]:
    """Every reading of every number in a text ("1.615" → 1615 and 1.615)."""
    out: set[float] = set()
    for raw in _NUM.findall(text or ""):
        for cand in (raw.replace(".", "").replace(",", "."), raw.replace(",", ""), raw.replace(",", ".")):
            try:
                out.add(float(cand))
            except ValueError:
                continue
    return out


def near(a: float, b: float, tol: tuple[str, float]) -> bool:
    kind, t = tol
    return abs(a - b) <= (t if kind == "abs" else t * abs(b)) + 1e-9


def _tight(b: float) -> tuple[str, float]:
    return ("abs", max(0.5 if abs(b) >= 50 else 0.0, TIGHT * abs(b)))


def _truths(c: BlameCase) -> list[float]:
    return [t for t in (c.truth, *c.truth_alternatives) if t is not None]


def _readings(c: BlameCase) -> list[float]:
    """The truth in every accepted unit (canonical and the other units of the attribute)."""
    out = _truths(c)
    for factor in UNIT_RULES.get(c.attribute or "", {}).values():
        out += [t / factor for t in _truths(c)]
    return out


def _in(text: str, values: list[float]) -> bool:
    nums = numbers(text)
    return any(near(n, v, _tight(v)) for v in values for n in nums)


def _reader(c: BlameCase) -> str:
    return "parser" if c.producer == "reader" else "extractor"


def _units(c: BlameCase) -> str | None:
    if c.claim_value is None:
        return None
    if (c.hybrid and c.attribute in ("max_power", "max_torque")
            and (c.truth is None or c.claim_value < c.truth)
            and any(w in f"{c.excerpt.lower()} " for w in ENGINE_WORDS)):  # fmt: skip
        return f"sense.engine_vs_system_{'torque' if c.attribute == 'max_torque' else 'power'}"
    if c.truth is None:
        return None
    best: tuple[float, str] | None = None
    for rule, factor in UNIT_RULES.get(c.attribute or "", {}).items():
        for n in numbers(c.excerpt):
            if near(n, c.claim_value, _tight(c.claim_value)) and near(n * factor, c.truth, c.tolerance):
                err = abs(n * factor - c.truth)
                if best is None or err < best[0]:
                    best = (err, rule)
    return best[1] if best else None


def blame_vector(c: BlameCase) -> Blame:
    truths = _truths(c)
    medium = c.truth_confidence.upper() == "MEDIUM"
    # 1. fusion
    if c.claim_value is not None and truths and any(near(c.claim_value, t, c.tolerance) for t in truths):
        if c.selected_value is not None and not any(near(c.selected_value, t, c.tolerance) for t in truths):
            return Blame({"fusion": 1.0}, "fusion", medium)
        return Blame({}, "not_wrong")
    on_excerpt = bool(truths) and _in(c.excerpt, _readings(c))
    on_page = on_excerpt or (bool(truths) and _in(c.page_text, _readings(c)))
    # 2. relevance
    sibling = c.claim_value is not None and any(near(c.claim_value, s, c.tolerance) for s in c.siblings)
    if (c.relevance or "").upper() in VAGUE_RELEVANCE or sibling:
        if on_page:
            return Blame({"relevance": 0.5, _reader(c): 0.5}, "relevance", medium)
        return Blame({"relevance": 1.0}, "relevance", medium)
    # 3. units / sense
    rule_id = _units(c)
    if rule_id:
        return Blame({"units_sense": 1.0}, "units_sense", medium, rule_id)
    # 4. our reading
    if on_page:
        return Blame({_reader(c): 1.0}, _reader(c), medium or not on_excerpt)
    # 5. the source said it
    return Blame({"source": 1.0}, "source", medium and bool(truths))


def component_keys(c: BlameCase, b: Blame) -> dict[str, str]:
    """Identity of every blamed component: `km77@v1`, `extract_specs@v3|<model>`, the rule id, `merge@1`, the
    relevance method, the source's domain."""
    keys = {
        "source": c.domain,
        "parser": c.producer_version or "unknown",
        "extractor": f"{c.producer_version or 'unknown'}|{c.model or 'unknown'}",
        "units_sense": b.rule_id or "unknown",
        "fusion": FUSION_KEY,
        "relevance": c.relevance_version or "page_relevance",
    }
    return {k: keys[k] for k, share in b.vector.items() if share > 0}
