"""Today's site readers become version 1 of their parser specs (spec 011 T086, contracts/parser-spec.md "v1 migration").

`migrate_v1(reader, block)` converts one `config/site_readers.yaml` entry (pure); `seed()` inserts `parsers` +
`parser_versions` `<reader>@v1` (`active`, author `seed`; a reader whose domains are deny-listed — `auto_data` —
is stored `retired`). Idempotent: an existing reader or version is left as it is. Run by the worker on start and by
`python -m automind.cli parsers-migrate-v1`. After the migration the YAML is read only here and as the
registry's fallback when the database has no parser.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from automind.acquisition.parsing.spec import FieldRule, ParserSpec
from automind.shared.provenance.versions import spec_hash

V1_NOTES = "v1: today's reader, migrated from config/site_readers.yaml"


def migrate_v1(reader: str, block: Mapping[str, Any]) -> ParserSpec:
    fields = [
        FieldRule(attribute=str(s["attribute"]), label=str(label), prefix=bool(s.get("prefix", False)),
                  unit=s.get("unit"), prefer_unit=s.get("prefer_unit"), text=bool(s.get("text", False)))
        for label, s in (block.get("labels") or {}).items()
    ]  # fmt: skip
    return ParserSpec(reader=reader, version=1, domains=[str(d) for d in block.get("domains") or []],
                      layout=str(block.get("pairs", "table")), fields=fields, notes=V1_NOTES)  # type: ignore[arg-type]  # fmt: skip


def yaml_specs() -> dict[str, ParserSpec]:
    from automind.shared.infrastructure.config.loader import load_yaml  # noqa: PLC0415

    return {k: migrate_v1(k, v) for k, v in load_yaml("site_readers.yaml").items() if k != "version"}


def denylist() -> list[str]:
    from automind.shared.infrastructure.config.loader import load_yaml  # noqa: PLC0415

    return [str(x).lower() for x in load_yaml("sources.yaml").get("denylist") or []]


def denied(spec: ParserSpec, deny: list[str]) -> bool:
    return any(x and x in d for d in spec.domains for x in deny)


async def seed() -> dict[str, Any]:
    from sqlalchemy.dialects.postgresql import insert  # noqa: PLC0415

    from automind.shared.infrastructure.db import Parser, ParserVersion, sessionmaker  # noqa: PLC0415

    deny = denylist()
    out: dict[str, Any] = {"inserted": [], "retired": []}
    now = datetime.now(UTC)
    async with sessionmaker()() as s:
        for reader, spec in yaml_specs().items():
            retired = denied(spec, deny)
            body = spec.model_dump(mode="json")
            await s.execute(insert(Parser).values(
                reader=reader, domains=spec.domains, page_type=spec.page_type,
                active_version=None if retired else 1, frozen=False, created_at=now,
            ).on_conflict_do_nothing(index_elements=["reader"]))  # fmt: skip
            got = await s.execute(insert(ParserVersion).values(
                key=spec.key, reader=reader, version=1, spec=body, spec_hash=spec_hash(body),
                status="retired" if retired else "active", zero_streak=0, author="seed", created_at=now,
                activated_at=None if retired else now,
            ).on_conflict_do_nothing(index_elements=["key"]).returning(ParserVersion.key))  # fmt: skip
            if got.scalar_one_or_none():
                out["inserted"].append(spec.key)
            if retired:
                out["retired"].append(spec.key)
        await s.commit()
    return out
