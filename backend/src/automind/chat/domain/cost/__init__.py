"""Chat · chat.domain.cost: what a car costs to run and own, and what a research turn costs — pure arithmetic.

Owns: `energy` — energy cost per powertrain (ICE/hybrid real-world figures, PHEV/EREV electric share, EV);
  `tco` — ownership cost items (maintenance, energy, tyres, road tax, depreciation, used-car reserves);
  `incentives` — DGT environmental label, incentive status, break-even; `turn_cost` — research cost estimate.
Depends on: nothing outside the standard library. Must not depend on: sqlalchemy, langgraph, fastapi, httpx,
  chat.application, chat.dialog.
Note: `turn_cost` (LLM/search spend of a turn) is not car ownership cost; `energy`/`tco` become packages in S5.
Public API: the modules in __all__ (callers import from them).
"""

__all__ = ["energy", "incentives", "tco", "turn_cost"]
