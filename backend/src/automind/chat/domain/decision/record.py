"""One policy pass as stored (spec 015 D5): plain data the `DecisionLog` port writes and reads back.

A record holds the situation without the case (the case is stored by version in `case_files`), the config by its
hash (the config itself in `policy_configs`), the rules' version, the trail of every rule asked, the rule that
decided, the action and the node the graph went to. Enough to say why, and to decide the pass again."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from automind.shared.contracts.json import JsonObject


class TrailStep(BaseModel):
    """One rule asked in a pass: its name, whether it fired, and why."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule: str
    fired: bool
    why: str


class DecisionRecord(BaseModel):
    """One pass of the policy in a turn; `(turn_id, pass_no)` is its key."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chat_id: str
    turn_id: str
    pass_no: int = Field(ge=1)
    case_version: int = Field(ge=0)
    situation: JsonObject  # the `Situation` as JSON without its case
    config_hash: str
    rules_version: str
    trail: tuple[TrailStep, ...]
    decided_by: str
    action: JsonObject  # the `Action` as JSON
    next_node: str
