"""Chat · chat.application.services.understanding (spec 013 S3): one message read into an `Intent`.

Owns: `checks` — code checks of the facts a model read (shared with the old interpreter until S4);
  `understander` — the one model call (`Understander`, prompt `understander.md`);
  `validate` — `validate_understanding`: the checks over an `Understanding`, plus the open question's ids;
  `resolver` — `IntentResolver`, the only place that corrects an understanding, each correction an `Override`;
  `shadow` — `UnderstandingShadow`: the chain run beside the old interpreter, recorded (S3; the old one decides).
Depends on: chat.domain, shared.contracts. Must not depend on: the dialog, infrastructure (import contract
  application-ports).
Public API: import from the modules (`from automind.chat.application.services.understanding.resolver import …`).
"""

__all__ = ["checks", "engine", "resolver", "rules", "shadow", "understander", "validate"]
