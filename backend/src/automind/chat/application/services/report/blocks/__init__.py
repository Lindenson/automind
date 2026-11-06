"""Chat · chat.application.services.report.blocks: one module per block of the report or card (the UI's data).

Owns: `spec_table`, `metric_bars`, `race`, `sources`, `data_panel`, `criteria`, `case_summary`, `engineering`,
  `manufacturer`, `tco`, `reliability`, `reviews`, `value_retention`, `electric` — the report's blocks;
  `car_view` — each car's version line and "Change" options; `intake_card` — the intake confirmation card.
Flow: built from the cars' facts (report.facts) and the domain's results; ordered by the dialog's report layout.
Depends on: report.facts, chat.domain, acquisition.api. Must not depend on: chat.dialog, the database.
Public API: the modules in __all__.
"""

__all__ = ["car_view", "case_summary", "criteria", "data_panel", "electric", "engineering", "intake_card",
           "manufacturer", "metric_bars", "race", "reliability", "reviews", "sources", "spec_table", "tco",
           "value_retention"]  # fmt: skip
