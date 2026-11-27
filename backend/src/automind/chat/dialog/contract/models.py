"""The two shapes of a node contract (spec 014 D2): `NodeIn`, the state keys a node reads, and `NodeOut`, the keys it
writes. Over today's flat `TurnState` keys (step C1): a field is a state key; a required input field is a key the node
cannot run without, an `Out` field without a default is a key the node writes on every branch.

Nested values (a notice list, the research plan, a JSON payload) are declared with their type and `SkipValidation`:
the checkpoint keeps exactly the plain data a node produced (no copy, no coercion, no class instance); scalar keys
are validated. Typed sections replace the flat keys at step C3.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

TurnUpdate = dict[str, object]  # what a node returns to LangGraph: state key → new value (plain data)


class NodeIn(BaseModel):
    """Base of a node's input: built from the turn state by `@node` (keys it does not declare are ignored)."""

    model_config = ConfigDict(frozen=True, extra="ignore", use_enum_values=True)


class NodeOut(BaseModel):
    """Base of a node's output: only declared keys (an extra key is an error); only the keys set are written."""

    model_config = ConfigDict(frozen=True, extra="forbid", use_enum_values=True)

    def update(self) -> TurnUpdate:
        """The state update: exactly the keys the node set (a key left out is not written), values as given."""
        return {k: getattr(self, k) for k in type(self).model_fields if k in self.model_fields_set}

    @classmethod
    def always_written(cls) -> frozenset[str]:
        """The keys every branch of the node writes (fields without a default)."""
        return frozenset(k for k, f in cls.model_fields.items() if f.is_required())


def required_reads(model: type[NodeIn]) -> frozenset[str]:
    """The keys a node cannot run without (fields without a default)."""
    return frozenset(k for k, f in model.model_fields.items() if f.is_required())
