"""JSON documents at the edge: the blocks of a reply, event payloads and card items the UI renders
(contracts/chat-protocol.md), and a config section as loaded from YAML before code reads it. Their shape is the UI's
or the config file's contract, not a type of the application: a `JsonObject` is the one sanctioned loose type
(code-shape.md "Public API of a layer", rule 1) and is used only for such a document — never for a collaborator, a
domain value or a result the application reads back."""

from __future__ import annotations

from typing import Any

JsonObject = dict[str, Any]  # a JSON object as built for the UI (values: str, int, float, bool, None, lists, objects)
