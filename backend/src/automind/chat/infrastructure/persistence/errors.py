"""The stores' failure contract (application/ports.py): no driver exception leaves a store. A failed statement or
an unreachable database becomes `StoreUnavailable` with the cause chained; the ports' own errors pass through."""

from __future__ import annotations

from automind.chat.application.ports import StoreUnavailable
from automind.shared.infrastructure.db.errors import translate_errors

store_errors = translate_errors(StoreUnavailable)
