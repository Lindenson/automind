"""Today's site readers become version 1 of their parser specs (spec 011 T086, contracts/parser-spec.md "v1 migration").

`migrate_v1(reader, block)` converts one `config/site_readers.yaml` entry; `denied` says whether a spec reads a
deny-listed domain (`auto_data`). Pure: the YAML is read and the versions are stored by `infrastructure/v1_specs.py`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from automind.acquisition.parsing.readers.spec import FieldRule, ParserSpec

V1_NOTES = "v1: today's reader, migrated from config/site_readers.yaml"


def migrate_v1(reader: str, block: Mapping[str, Any]) -> ParserSpec:
    """Version 1 of the reader `reader` from its `site_readers.yaml` entry (labels, layout `pairs`, domains)."""
    fields = [
        FieldRule(attribute=str(s["attribute"]), label=str(label), prefix=bool(s.get("prefix", False)),
                  unit=s.get("unit"), prefer_unit=s.get("prefer_unit"), text=bool(s.get("text", False)))
        for label, s in (block.get("labels") or {}).items()
    ]  # fmt: skip
    layout = str(block.get("pairs", "table"))  # validated as `Layout` by the model
    domains = [str(d) for d in block.get("domains") or []]
    return ParserSpec.model_validate(
        {"reader": reader, "version": 1, "domains": domains, "layout": layout, "fields": fields, "notes": V1_NOTES}
    )


def denied(spec: ParserSpec, deny: list[str]) -> bool:
    """Whether one of the spec's domains contains a deny-listed name."""
    return any(x and x in d for d in spec.domains for x in deny)
