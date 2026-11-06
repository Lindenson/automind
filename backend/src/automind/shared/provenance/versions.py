"""Version identifiers of readers, prompts, models and specs (spec 011 research R2). Pure.

Plain text keys everywhere, no foreign keys between versioned objects and values: `km77@v1` (parser spec),
`extract_specs@v3` (extraction prompt), `provider:model` (model), `plan@1` (pipeline stage).
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

LEGACY = "legacy"
_HEADER = re.compile(r"<!--\s*prompt:\s*([\w-]+)\s+v(\d+)", re.I)
_KEY = re.compile(r"^([\w-]+)@v(\d+)$")


def reader_key(reader: str, version: int) -> str:
    """`km77@v1`; a `site:` prefix (as in `Page.reader`) is dropped."""
    return f"{reader.removeprefix('site:')}@v{int(version)}"


def prompt_key_from_header(text: str) -> tuple[str, int] | None:
    """(name, version) from a prompt's header comment `<!-- prompt: extract_specs v3 … -->`, else None."""
    m = _HEADER.search(text[:300])
    return (m.group(1), int(m.group(2))) if m else None


def prompt_key(text: str, name: str) -> str:
    """`extract_specs@v3` from the prompt's header; `<name>@legacy` when it has none."""
    got = prompt_key_from_header(text)
    return f"{got[0]}@v{got[1]}" if got else f"{name}@{LEGACY}"


def prompt_version_key(name: str, version: str | int | None) -> str:
    """`extract_specs@v3` from a name and a version as the gateway records it ("v3" or 3); `<name>@legacy`."""
    if version is None or version == "":
        return f"{name}@{LEGACY}"
    v = str(version).lstrip("v")
    return f"{name}@v{int(v)}" if v.isdigit() else f"{name}@{LEGACY}"


def parse_key(key: str) -> tuple[str, int]:
    """`km77@v12` -> ("km77", 12); raises ValueError for anything that is not `<name>@v<N>`."""
    m = _KEY.match(key)
    if not m:
        raise ValueError(f"not a version key: {key!r}")
    return m.group(1), int(m.group(2))


def spec_hash(spec: Any) -> str:
    """sha256[:12] of the canonical JSON (sorted keys, no spaces) of a spec."""
    canon = json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:12]
