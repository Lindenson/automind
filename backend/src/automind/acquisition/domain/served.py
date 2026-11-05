"""Which model and prompt version actually answered a call (spec 011 T009, FR-002, research R2). Pure.

The LLM gateway calls `begin(role)` at the start of each structured/text call; the usage callback calls `record()`
when the model answered. `served(role)` then tells the caller, in the same task, which model and prompt version
produced the output, so a claim can name its producer. The holder is a dict owned by the calling task's context, so
concurrent extractions (`asyncio.gather`) each see their own call, and a callback run in a copied context still
writes into it.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

from automind.acquisition.domain.versions import prompt_version_key

_LAST = "__last__"


@dataclass(frozen=True)
class ServedCall:
    role: str
    model: str
    prompt_name: str | None = None
    prompt_version: str | None = None  # "v3" as the gateway records it
    prompt_hash: str | None = None

    @property
    def prompt_key(self) -> str:
        """`extract_specs@v3`, or `<name>@legacy` for a prompt without a header."""
        return prompt_version_key(self.prompt_name or self.role, self.prompt_version)


_SERVED: ContextVar[dict[str, ServedCall] | None] = ContextVar("served_call", default=None)


def begin(role: str) -> None:
    """A new call of `role` starts in this context: forget the role's previous answer."""
    holder = {k: v for k, v in (_SERVED.get() or {}).items() if k not in (role, _LAST)}
    _SERVED.set(holder)


def record(call: ServedCall) -> None:
    """The model answered (called by the usage callback)."""
    holder = _SERVED.get()
    if holder is None:
        holder = {}
        _SERVED.set(holder)
    holder[call.role] = call
    holder[_LAST] = call


def served(role: str | None = None) -> ServedCall | None:
    """The last answered call of `role` (or of any role) in this context, else None."""
    holder = _SERVED.get() or {}
    return holder.get(role if role is not None else _LAST)
