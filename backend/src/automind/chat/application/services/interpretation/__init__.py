"""Chat · chat.application.services.interpretation: reads the person's message and words the questions back.

Owns: `interpret` — the LLM proposes a typed case delta (`Interpretation`); code checks car references
  (`InterpretError` instead of guessing); `ask` — up to 3 clarifying questions chosen by code from templates,
  phrased by the model in the person's language, plus intake questions and quick replies.
Depends on: chat.domain (case, policy, intake, identification), shared.contracts.llm, pydantic.
Must not depend on: chat.dialog, delivery.web, sqlalchemy, langgraph.
Public API: the modules in __all__ (callers import from them).
"""

__all__ = ["ask", "interpret"]
