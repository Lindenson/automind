"""Stage ask_model: the make is known, the model is not — the make's models are offered, the 1–3 that fit the person
first, marked as suggestions with machine reasons (spec 005 FR-008, FR-024)."""

from __future__ import annotations

from automind.chat.application.services.identification.contracts import KnownModels
from automind.chat.application.services.identification.stages.place_market import lineup_models
from automind.chat.domain import intake
from automind.chat.domain.case import CaseCar, CaseFile, Choice, Fit, IdentifyOutcome

MAX_MODELS = 6  # options offered


def ask_model(car: CaseCar, case: CaseFile, names: KnownModels, note: str | None) -> IdentifyOutcome:
    make = car.make or ""
    choices = _from_lineup(names, make, case) or [
        Choice(label=f"{make} {m}", make=make, model=m) for m in sorted(names.known)[:MAX_MODELS]
    ]
    return IdentifyOutcome(outcome="CHOICES" if choices else "NEED", need="MODEL", choices=choices, note=note)


def _from_lineup(names: KnownModels, make: str, case: CaseFile) -> list[Choice]:
    models = lineup_models(names.lineup)
    ranked = intake.rank_lineup(models, Fit.from_case(case))
    why = {m.model: r for m, r in ranked if r}
    order = [m for m, _ in ranked if m.model in why] + [m for m in models if m.model not in why]
    out = []
    for m in order[:MAX_MODELS]:
        pts = ", ".join(m.powertrains) if getattr(m, "powertrains", None) else None
        bits = ", ".join(x for x in (getattr(m, "body", "") or "", pts or "") if x)
        out.append(Choice(label=f"{make} {m.model}" + (f" ({bits})" if bits else ""), make=make, model=m.model,
                          body=getattr(m, "body", None) or None, powertrain=pts,
                          source_url=getattr(m, "source_url", None),
                          price_from_eur=getattr(m, "price_from_eur", None),
                          suggested=m.model in why, reason=",".join(why.get(m.model, [])) or None))  # fmt: skip
    return out
