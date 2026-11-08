"""The version-1 parser specs from the owner's config files, and their seed into the database (spec 011 T086).

`yaml_specs()` reads `config/site_readers.yaml` as v1 specs, `denylist()` the deny-list of `config/sources.yaml`.
`seed()` inserts `parsers` + `parser_versions` `<reader>@v1` (`active`, author `seed`; a reader whose domains are
deny-listed — `auto_data` — is stored `retired`). Idempotent: an existing reader or version is left as it is. Run by
the worker on start and by `python -m automind.cli parsers-migrate-v1`. After the migration the YAML is read only
here and as the registry's fallback when the database has no parser.
Errors: `ParserStoreUnavailable` when the database fails (nothing is stored: one transaction).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TypedDict

from sqlalchemy.dialects.postgresql import insert

from automind.acquisition.parsing.readers.migrate_v1 import denied, migrate_v1
from automind.acquisition.parsing.readers.ports import ParserStoreUnavailable
from automind.acquisition.parsing.readers.spec import ParserSpec
from automind.shared.infrastructure.config.loader import load_yaml
from automind.shared.infrastructure.db import Parser, ParserVersion
from automind.shared.infrastructure.db.errors import translate_errors
from automind.shared.infrastructure.db.session import sessionmaker
from automind.shared.provenance.versions import spec_hash


class Seeded(TypedDict):
    """What the seed did: the version keys it inserted and those stored retired (deny-listed)."""

    inserted: list[str]
    retired: list[str]


def yaml_specs() -> dict[str, ParserSpec]:
    """Version 1 of every reader in `config/site_readers.yaml`, by reader name."""
    return {k: migrate_v1(k, v) for k, v in load_yaml("site_readers.yaml").items() if k != "version"}


def denylist() -> list[str]:
    """The owner's deny-list (`config/sources.yaml`), lowercased."""
    return [str(x).lower() for x in load_yaml("sources.yaml").get("denylist") or []]


@translate_errors(ParserStoreUnavailable)
async def seed() -> Seeded:
    """Store version 1 of every YAML reader that is not in the database yet (one transaction)."""
    deny = denylist()
    out = Seeded(inserted=[], retired=[])
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
