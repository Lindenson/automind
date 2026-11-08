"""The registry's services wired over the database, the snapshot store, the fetcher and the model, with
`config/registry.yaml` (loaded when no mapping is given) and the deny-list of `config/sources.yaml`. Callers use
these, never the stores directly."""

from __future__ import annotations

from datetime import UTC, datetime

from automind.acquisition.registry.application.admission import SiteAdmission
from automind.acquisition.registry.application.ports import SiteFacts
from automind.acquisition.registry.application.review import DailyReview
from automind.acquisition.registry.application.seed import RegistrySeed, SeedSources
from automind.acquisition.registry.application.service import RegistryService
from automind.acquisition.registry.domain.config import RegistryConfig
from automind.acquisition.registry.infrastructure import seed_config
from automind.acquisition.registry.infrastructure.admission_store import AdmissionStore
from automind.acquisition.registry.infrastructure.capability_store import CapabilityStore
from automind.acquisition.registry.infrastructure.pages import SnapshotMarks
from automind.acquisition.registry.infrastructure.review_store import ReviewStore
from automind.acquisition.registry.infrastructure.seed_store import SeedStore
from automind.acquisition.registry.infrastructure.signal_store import SignalStore
from automind.acquisition.registry.infrastructure.terms import StructuredLLM, TermsFacts
from automind.shared.contracts.json import JsonObject
from automind.shared.infrastructure.config.loader import load_yaml


class SystemClock:
    """The system time (UTC)."""

    def now(self) -> datetime:
        """Now."""
        return datetime.now(UTC)


def registry_config(raw: JsonObject | None = None) -> RegistryConfig:
    """`raw` (a `registry.yaml` mapping) typed; the file when None."""
    return RegistryConfig.from_mapping(raw if raw is not None else load_yaml("registry.yaml"))


def registry_service(raw: JsonObject | None = None) -> RegistryService:
    """The registry port's service (`registry.api.RegistryPort`)."""
    cfg = registry_config(raw)
    return RegistryService(CapabilityStore(cfg), SignalStore(cfg), SnapshotMarks(), cfg)


def signal_store(raw: JsonObject | None = None) -> SignalStore:
    """The truth signals' store (the blame judge settles disputed signals with it)."""
    return SignalStore(registry_config(raw))


def site_admission(raw: JsonObject | None = None, llm: StructuredLLM | None = None,
                   facts: SiteFacts | None = None) -> SiteAdmission:  # fmt: skip
    """The admission check; `facts` gathers from the sites (fetcher and terms reader over `llm` when None)."""
    return SiteAdmission(AdmissionStore(), facts or TermsFacts(llm), registry_config(raw), seed_config.denylist(),
                         SystemClock())  # fmt: skip


def daily_review(raw: JsonObject | None = None, facts: SiteFacts | None = None) -> DailyReview:
    """The daily review, with the admission of new sites first."""
    cfg = registry_config(raw)
    deny = seed_config.denylist()
    admission = SiteAdmission(AdmissionStore(), facts or TermsFacts(), cfg, deny, SystemClock())
    return DailyReview(ReviewStore(cfg), admission, cfg, deny, SystemClock())


def registry_seed() -> RegistrySeed:
    """The seed from the favourites and the 009 survey."""
    families = registry_config().families
    sources = SeedSources(seed_config.favourites(), seed_config.survey(), seed_config.denylist(), families)
    return RegistrySeed(SeedStore(), sources)
