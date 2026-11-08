"""The site readers wired over the database, the config files and the shadow gate. Callers use these functions,
never the stores' constructors."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from automind.acquisition.domain import drift
from automind.acquisition.gates.infrastructure.wiring import LiveShadowFeed
from automind.acquisition.infrastructure.config import acquisition_config
from automind.acquisition.parsing.infrastructure.parser_store import ParserStore
from automind.acquisition.parsing.infrastructure.reading_log import ReadingLogStore
from automind.acquisition.parsing.infrastructure.v1_specs import denylist, yaml_specs
from automind.acquisition.parsing.readers.migrate_v1 import denied
from automind.acquisition.parsing.readers.registry import ParserRegistry
from automind.acquisition.parsing.readers.spec import ParserSpec
from automind.shared.infrastructure.config import loader


def parser_store() -> ParserStore:
    """The stored parser versions."""
    return ParserStore()


def parser_registry(specs: Iterable[ParserSpec] = (), *, allowed: Iterable[str] | None = None, live: bool = False,
                    cfg: drift.DriftConfig | None = None) -> ParserRegistry:  # fmt: skip
    """A registry over the database: `specs` run until a refresh finds stored versions (`live` refreshes itself)."""
    return ParserRegistry(ParserStore(), ReadingLogStore(), LiveShadowFeed(), specs, allowed=allowed, live=live,
                          cfg=cfg)  # fmt: skip


def yaml_registry(favourites: Sequence[Mapping[str, Any]] | None = None, *, live: bool = False,
                  cfg: drift.DriftConfig | None = None) -> ParserRegistry:  # fmt: skip
    """Version 1 of today's readers; with `favourites`, only for those with a reader whose terms were reviewed.
    Deny-listed readers (auto_data) never run."""
    deny = denylist()
    specs = [s for s in yaml_specs().values() if not denied(s, deny)]
    allowed = None
    if favourites is not None:
        allowed = [str(f["domain"]) for f in favourites if f.get("reader") and f.get("tos_checked")]
    return parser_registry(specs, allowed=allowed, live=live, cfg=cfg)


def live_readers() -> ParserRegistry:
    """The engine's site readers: the YAML v1 readers of the reviewed favourites until the database has versions."""
    cfg = drift.DriftConfig.from_mapping(acquisition_config().get("drift"))
    return yaml_registry(loader.favourites(), live=True, cfg=cfg)
