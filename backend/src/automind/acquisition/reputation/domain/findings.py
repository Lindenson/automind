"""The signal rules (spec 011 FR-010/FR-011, research R7-R9), pure: from a version's facts, the signals to emit —
`gold` (a claim against its gold value; a wrong selection although a claim was right is `fusion`), `physics` (the
outlier of the R8 checks), `agreement` (k independent families agree), `replacement` (a value shown alone lost to a
more confident selection). Each skips what was signalled before; blame is computed later from the stored page."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping

from automind.acquisition.domain import agreement, physics, replacement
from automind.acquisition.domain.blame import BlameCase, blame_vector, component_keys, near
from automind.acquisition.domain.tolerance import Tolerance
from automind.acquisition.domain.truth import TruthKind as K
from automind.acquisition.domain.truth import TruthVerdict as V
from automind.acquisition.reputation.domain.signal_facts import (
    BlameAsk,
    ClaimFact,
    Finding,
    GoldFact,
    VariantFacts,
)
from automind.shared.contracts.json import JsonObject

FUSION_KEY = "fusion:merge@1"


def tolerance(attribute: str, tolerances: Mapping[str, Tolerance], gold: GoldFact | None = None) -> Tolerance:
    """The gold value's own tolerance, else the attribute's."""
    if gold is not None and gold.tolerance is not None:
        return gold.tolerance
    return tolerances[attribute]


def gold_findings(f: VariantFacts, tolerances: Mapping[str, Tolerance]) -> list[Finding]:
    """Every accepted numeric claim with a gold value: right within tolerance, else wrong with blame."""
    out: list[Finding] = []
    for c in f.claims:
        g = f.gold.get(c.attribute)
        if g is None or g.value_num is None or c.value_num is None or (c.id, "gold") in f.done:
            continue
        tol = tolerance(c.attribute, tolerances, g)
        details: JsonObject = {"gold": g.value_num, "value": c.value_num, "rule": g.match_rule}
        if near(c.value_num, g.value_num, tol):
            out.append(Finding(K.GOLD, V.RIGHT, c.attribute, "gold_right", details, claim=c, gold_id=g.id))
        else:
            ask = BlameAsk(g.value_num, tol, g.confidence)
            out.append(Finding(K.GOLD, V.WRONG, c.attribute, "gold_wrong", details, claim=c, gold_id=g.id, blame=ask))
    return out


def fusion_findings(f: VariantFacts, tolerances: Mapping[str, Tolerance]) -> list[Finding]:
    """A selected value wrong against gold although one of the claims behind the attribute was right."""
    out: list[Finding] = []
    for attr, sv in f.selected.items():
        g = f.gold.get(attr)
        if g is None or g.value_num is None or sv.value_num is None or not sv.available:
            continue
        tol = tolerance(attr, tolerances, g)
        if near(sv.value_num, g.value_num, tol) or (attr, float(sv.value_num)) in f.fused:
            continue
        right = [c for c in f.claims if c.attribute == attr and c.value_num is not None
                 and near(c.value_num, g.value_num, tol)]  # fmt: skip
        if right:
            out.append(Finding(K.GOLD, V.WRONG, attr, "fusion", {"selected": float(sv.value_num), "gold": g.value_num},
                               domain=right[0].domain, area=right[0].area, gold_id=g.id,
                               fixed_blame=({"fusion": 1.0}, {"fusion": "merge@1"})))  # fmt: skip
    return out


def physics_findings(f: VariantFacts, tolerances: Mapping[str, Tolerance], checks: JsonObject) -> list[Finding]:
    """The claims behind the one value the physics checks single out."""
    values = {a: float(sv.value_num) for a, sv in f.selected.items() if sv.available and sv.value_num is not None}
    by_id = {c.id: c for c in f.claims}
    fams = {a: len({by_id[i].family for i in sv.claim_ids if i in by_id}) or 1 for a, sv in f.selected.items()}
    drive = f.selected.get("drivetrain")
    drivetrain = ((drive.value_text or "").upper() or None) if drive else None
    o = physics.outlier(physics.Facts(values, f.fuel, f.powertrain, drivetrain, f.body_class, fams), checks)
    if o.attribute is None:
        return []
    inc = next(i for i in o.inconsistencies if o.attribute in i.values)
    details: JsonObject = {"check": inc.check, "values": inc.values, "about": inc.about, "expected": list(inc.expected),
                           "outlier_rule": o.rule}  # fmt: skip
    ask = BlameAsk(None, tolerances[o.attribute])
    ids = [cid for cid in f.selected[o.attribute].claim_ids if cid in by_id and (cid, "physics") not in f.done]
    claims = [by_id[cid] for cid in ids]
    return [Finding(K.PHYSICS, V.WRONG, o.attribute, "physics", details, claim=c, blame=ask) for c in claims]


def agreement_findings(f: VariantFacts, tolerances: Mapping[str, Tolerance]) -> list[Finding]:
    """One right signal per family whose values agree with k independent families, once per family."""
    by_attr: dict[str, list[agreement.FamilyValue]] = defaultdict(list)
    for c in f.claims:
        if c.value_num is not None:
            by_attr[c.attribute].append(agreement.FamilyValue(c.id, c.domain, c.family, float(c.value_num)))
    by_id = {c.id: c for c in f.claims}
    out: list[Finding] = []
    seen = set(f.agreed)
    for attr, vals in by_attr.items():
        for a in agreement.agreements(vals, tolerance(attr, tolerances, f.gold.get(attr))):
            if (attr, a.family) in seen:
                continue
            details: JsonObject = {"family": a.family, "families": a.families, "value": a.value}
            out.append(Finding(K.AGREEMENT, V.RIGHT, attr, "agreement", details, claim=by_id[a.claim_id]))
            seen.add((attr, a.family))
    return out


def replacement_findings(f: VariantFacts, tolerances: Mapping[str, Tolerance]) -> list[Finding]:
    """A value shown alone that lost to a more confident selection is wrong (never disputed: no judge needed)."""
    by_id = {c.id: c for c in f.claims}
    out: list[Finding] = []
    for attr, sv in f.selected.items():
        if not sv.available or sv.value_num is None or (sv.confidence or "").upper() not in ("HIGH", "MEDIUM"):
            continue
        hist = [replacement.Seen(c.id, c.domain, float(c.value_num), c.created_at.timestamp())
                for c in f.claims if c.attribute == attr and c.value_num is not None]  # fmt: skip
        for old in replacement.replaced(hist, sv.claim_ids, float(sv.value_num), tolerances[attr]):
            if (old.claim_id, "replacement") in f.done:
                continue
            details: JsonObject = {"replaced_by": float(sv.value_num), "judge": "not needed"}
            ask = BlameAsk(float(sv.value_num), tolerances[attr], "MEDIUM", may_dispute=False)
            out.append(Finding(K.REPLACEMENT, V.WRONG, attr, "replacement", details, claim=by_id[old.claim_id],
                               blame=ask))  # fmt: skip
    return out


def blamed(
    f: VariantFacts, c: ClaimFact, ask: BlameAsk, page_text: str
) -> tuple[dict[str, float], dict[str, str], bool]:
    """The blame vector of a wrong claim (research R9), the identity of each blamed component and whether the blame
    is disputed (a judge settles it). `page_text`: the stored page, or the cached text when there is no truth."""
    sv = f.selected.get(c.attribute)
    verdict, rel_version = f.relevance.get(c.doc_id or "", (None, None))
    case = BlameCase(
        attribute=c.attribute, claim_value=c.value_num, truth=ask.truth, tolerance=ask.tolerance,
        selected_value=sv.value_num if sv is not None and sv.available else None, producer=c.producer,
        producer_version=c.producer_version, model=c.model, relevance=verdict, relevance_version=rel_version,
        siblings=f.siblings.get(c.attribute, ()), excerpt=c.excerpt, page_text=page_text,
        truth_confidence=ask.confidence, hybrid=f.hybrid, domain=c.domain,
    )  # fmt: skip
    b = blame_vector(case)
    vector = b.vector or {"source": 1.0}
    return vector, component_keys(case, b) if b.vector else {"source": c.domain}, b.disputed and ask.may_dispute
