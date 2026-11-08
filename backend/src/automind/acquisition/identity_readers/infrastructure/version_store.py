"""The dataset groups known offline (`VersionBook` over the database): the EEA CO2 group keys stored with the gold
values of a model's catalogue variants (`gold_values.record_key` joined with `vehicle_variants`), and the rows of a
make cached by a live query (`search_cache`, provider `dataset`). Every method raises `IdentityStoreUnavailable`
when the database fails."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from automind.acquisition.gold.domain.text import norm_text
from automind.acquisition.identity_readers.application.ports import IdentityStoreUnavailable
from automind.acquisition.identity_readers.domain.registered import IdRow, rows_of_keys
from automind.shared.contracts.json import JsonObject
from automind.shared.infrastructure.db.errors import translate_errors
from automind.shared.infrastructure.db.models import GoldValueRow, SearchCache, Variant
from automind.shared.infrastructure.db.session import sessionmaker

DATASET = "eea_co2"
PROVIDER = "dataset"


class VersionStore:
    """`VersionBook` over the database."""

    @translate_errors(IdentityStoreUnavailable)
    async def stored(self, make: str, model: str) -> list[IdRow]:
        """The EEA groups matched to the model's catalogue variants by the last gold load."""
        async with sessionmaker()() as s:
            q = (
                select(GoldValueRow.record_key).distinct()
                .join(Variant, Variant.id == GoldValueRow.variant_id)
                .where(func.lower(Variant.make) == make.lower(), func.lower(Variant.model) == model.lower(),
                       GoldValueRow.dataset_id.like(f"{DATASET}%"), GoldValueRow.record_key.is_not(None))
            )  # fmt: skip
            keys = [k for k in (await s.execute(q)).scalars() if k]
        return rows_of_keys(keys, DATASET)

    @translate_errors(IdentityStoreUnavailable)
    async def cached(self, make: str) -> list[IdRow] | None:
        """The make's dataset rows cached by an earlier live query; None when not cached (or expired)."""
        async with sessionmaker()() as s:
            row = await s.get(SearchCache, cache_key(make))
        if row is None or row.expires_at <= datetime.now(UTC):
            return None
        return [IdRow(*x) for x in row.hits or []]

    @translate_errors(IdentityStoreUnavailable)
    async def cache(self, make: str, rows: list[IdRow], days: float) -> None:
        """Keep the make's rows for `days` (an empty list marks the make as asked)."""
        now = datetime.now(UTC)
        values: JsonObject = {
            "key": cache_key(make), "provider": PROVIDER, "query": f"{DATASET} {make}"[:2000], "gl": "-", "hl": "-",
            "hits": [_to_json(r) for r in rows], "fetched_at": now, "empty": not rows,
            "expires_at": now + timedelta(days=days),
        }  # fmt: skip
        async with sessionmaker()() as s:
            await s.execute(insert(SearchCache).values(**values).on_conflict_do_update(index_elements=["key"],
                                                                                        set_=values))  # fmt: skip
            await s.commit()


def cache_key(make: str) -> str:
    """The `search_cache` key of a make's dataset rows."""
    return hashlib.sha256(f"dataset_rows|{DATASET}|{norm_text(make)}".encode()).hexdigest()


def _to_json(r: IdRow) -> list[str | float | int | None]:
    return [r.dataset, r.make, r.model, r.fuel, r.engine_kw, r.displacement_cc, r.year_from, r.year_to, r.registrations]
