"""Chat · chat: the car-advice conversation — understand the person, identify the cars, research, answer.

Owns: `domain` — pure rules (case file, identification, cost, assessment, verdict, action policy);
  `application` — ports, services and use cases that apply those rules to stored data;
  `dialog` — the LangGraph turn graph, its nodes, runner and the fixed reply texts;
  `infrastructure` — repositories, event bus, checkpointer and live port implementations.
Flow: delivery.web hands a message to dialog.runner → the turn graph (dialog.graph) runs its nodes →
  nodes call application services → services use domain rules and ports → infrastructure stores and publishes.
Depends on: shared, acquisition.api / acquisition.registry.api (data is ordered only there), observability.
Must not depend on: acquisition engine internals (pipeline, parsing, gold …), registry domain/application.
Public API: the modules in __all__ (callers import from them).
"""

__all__ = ["application", "dialog", "domain", "infrastructure"]
