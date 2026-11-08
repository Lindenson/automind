"""Gold's services wired over the database, the open-data loaders, the reference file and `config/gold_datasets.yaml`
(with `config/makes.yaml`). Callers use these, never the stores' construction."""

from __future__ import annotations

import httpx

from automind.acquisition.gold.application.challenges import ChallengeGold
from automind.acquisition.gold.application.load import DatasetGold, GoldLoad, ReferenceGold
from automind.acquisition.gold.application.ports import GoldSource
from automind.acquisition.gold.domain.config import GoldRules, MatchCfg
from automind.acquisition.gold.infrastructure.candidate_store import CandidateStore
from automind.acquisition.gold.infrastructure.gold_store import GoldStore
from automind.acquisition.gold.infrastructure.loaders import eea_co2, eea_obfcm, rdw
from automind.acquisition.gold.infrastructure.loaders.api_dataset import ApiDataset, Loader
from automind.acquisition.gold.infrastructure.loaders.reference_set import ReferenceFile
from automind.acquisition.infrastructure import config as acq_config
from automind.shared.contracts.json import JsonObject
from automind.shared.infrastructure.config import loader as config

LOADERS: dict[str, Loader] = {"eea_co2": eea_co2, "eea_obfcm": eea_obfcm, "rdw": rdw}
SOURCES = ("reference_set", *LOADERS)  # the load order of `gold-load --dataset all`


def gold_rules() -> GoldRules:
    """Each attribute's gold tolerance and unit."""
    return GoldRules.from_config(acq_config.gold_datasets_config())


def match_cfg() -> MatchCfg:
    """How dataset rows are matched to a variant."""
    return MatchCfg.from_config(acq_config.gold_datasets_config(), config.load_yaml("makes.yaml"))


def dataset_cfg(name: str) -> JsonObject:
    """The dataset's mapping under `datasets:` (what its loader takes)."""
    return dict((acq_config.gold_datasets_config().get("datasets") or {}).get(name) or {})


def gold_store() -> GoldStore:
    """The gold book."""
    return GoldStore()


def candidates() -> CandidateStore:
    """The catalogue variants gold is loaded for."""
    return CandidateStore()


def gold_load(transport: httpx.AsyncBaseTransport | None = None) -> GoldLoad:
    """The load of every source, in order: the reference set, EEA CO2, EEA OBFCM, RDW."""
    cfg = match_cfg()
    sources: dict[str, GoldSource] = {"reference_set": ReferenceGold(ReferenceFile(), gold_rules())}
    for name, loader in LOADERS.items():
        sources[name] = DatasetGold(ApiDataset(loader, dataset_cfg(name), transport), cfg)
    return GoldLoad(GoldStore(), sources)


def challenge_gold() -> ChallengeGold:
    """Gold from settled user challenges."""
    return ChallengeGold(GoldStore(), gold_rules())
