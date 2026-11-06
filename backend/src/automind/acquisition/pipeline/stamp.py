"""Producer identity of a claim (spec 011 FR-002, SC-002, research R2): source page, producer, version and model.

Keyword arguments for `db.Claim(...)` and `page_relevance`, so the research code names who produced each value
without growing. Reader claims name the parser spec version that read them (US4); extractor claims name
the prompt version and the model that actually answered the call in this task (the gateway's served call).
"""

from __future__ import annotations

from typing import Any

from automind.shared.provenance.served import served
from automind.shared.provenance.versions import parse_key, reader_key

LEGACY_READER_VERSION = 1


def reader(reading: Any, page: Any) -> dict[str, Any]:
    """`reading` is a `SiteReading` named by its parser version (`reader="km77@v2"`, spec 011 US4) — or, from an old
    reader, `"site:km77"` (version 1) — and `page` the `Page` it was read from (or None)."""
    name = str(reading.reader)
    try:
        parse_key(name)
        version = name
    except ValueError:
        version = reader_key(name.removeprefix("site:"), LEGACY_READER_VERSION)
    return {
        "producer": "reader",
        "producer_version": version,
        "model": None,
        "snapshot_id": getattr(page, "snapshot_id", None),
    }


def extractor(page: Any, role: str = "extractor") -> dict[str, Any]:
    """The extraction role's served call in this task: `extract_specs@v2` and the model that answered. `page` is the
    `Page` or the `WebDoc` made from it (both carry the snapshot id)."""
    call = served(role)
    return {
        "producer": "extractor",
        "producer_version": call.prompt_key if call else "legacy",
        "model": call.model if call else None,
        "snapshot_id": getattr(page, "snapshot_id", None),
    }


def relevance(method: str) -> dict[str, Any]:
    """`page_relevance` method, and the prompt version and model of the relevance role's verdict (LLM only)."""
    call = served("relevance") if method == "LLM" else None
    return {
        "method": method,
        "prompt_version": call.prompt_key if call else None,
        "model": call.model if call else None,
    }
