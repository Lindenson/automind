from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[6]  # repo root: shared/infrastructure/config/settings.py is 6 levels down


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(ROOT / ".env", ROOT / "backend" / ".env"), extra="ignore")

    database_url: str = f"postgresql+asyncpg://postgres@/automind?host={ROOT}/.pgdata/pg"

    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    # Gemini: GOOGLE_API_KEY, GEMINI_API_KEY or (as written in this project's .env) GEMENI_API_KEY
    google_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("GOOGLE_API_KEY", "GEMINI_API_KEY", "GEMENI_API_KEY")
    )
    tavily_api_key: str | None = None
    serper_api_key: str | None = None
    serpapi_api_key: str | None = None
    # overrides `provider` in config/search.yaml (e.g. SEARCH_PROVIDER=tavily for the baseline eval)
    search_provider: str | None = None

    # Per-turn limits (FR-041). Models per role live in config/models.yaml (constitution VII).
    max_llm_calls_per_turn: int = 160  # spec 003: more pages per area; the €1 cost cap still bounds a turn
    cost_confirm_threshold_eur: float = 0.30
    cost_hard_cap_eur: float = 1.00
    policy_max_passes: int = 8  # spec 007 FR-027: policy passes in one turn before the limit pass
    # spec 015 D6: a policy input that breaks an invariant fails the turn (tests) instead of a log line and a metric
    policy_strict: bool = Field(default=False, validation_alias="AUTOMIND_POLICY_STRICT")
    # spec 013 S3: the new understanding runs beside the old interpreter and is recorded; false reverts globally (G8)
    understanding_shadow: bool = Field(default=True, validation_alias="AUTOMIND_UNDERSTANDING_SHADOW")
    # spec 013 S4: the new understanding decides typed words (the old interpreter only when it refuses); false = S3
    understanding_decides: bool = Field(default=True, validation_alias="AUTOMIND_UNDERSTANDING_DECIDES")
    max_concurrency: int = 4
    job_timeout_s: float = 180.0  # one car × area; a slow source no longer cuts a job short
    turn_timeout_s: float = 900.0  # research pauses (and asks) at 85% of it; 300 s paused 3-car research
    max_docs_per_car: int = 8
    max_doc_chars: int = 14000
    request_timeout_s: int = 30
    extraction_concurrency: int = 4

    # cache freshness per category (days)
    fresh_specs_days: int = 365
    fresh_price_days: int = 30
    fresh_maintenance_days: int = 365

    # API bind address: 127.0.0.1 = this machine only; 0.0.0.0 = reachable from the local network
    # (there is no login yet: anyone on the network can use the hub; chats stay per browser and the daily cap
    # bounds the spend, see api/access.py and ADR-029).
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    # Access (before any external demo): each browser gets an anonymous owner cookie and sees only its own chats;
    # browser requests from other sites are refused (WebSocket and changes); internal endpoints (research metrics)
    # need ADMIN_TOKEN, or come from this machine when it is not set.
    owner_isolation: bool = True
    allowed_origins: list[str] = ["http://127.0.0.1:5173", "http://localhost:5173"]
    admin_token: str | None = None
    # spec 010 FR-030: Prometheus /metrics; without a token only these networks may scrape
    metrics_token: str | None = None
    metrics_nets: str = "127.0.0.0/8,::1/128,172.16.0.0/12"
    # spec 013 T006: the nightly understanding eval's summary (scripts/eval_understanding.sh; mounted into the app)
    understanding_eval_summary: str = "/eval-runs/understanding/latest.json"
    # Spend across all chats per day (Europe/Madrid): research pauses and asks "continue?" at it; 0 = no cap
    daily_cap_eur: float = 5.00

    # spec 014 T107: a broken graph node contract raises (tests) or is logged and counted (production, for now)
    contract_strict: bool = Field(default=False, validation_alias="AUTOMIND_CONTRACT_STRICT")

    frontend_dist: Path = ROOT / "frontend" / "dist"
    config_dir: Path = ROOT / "backend" / "config"

    def freshness_days(self, category: str) -> int:
        return {
            "specs": self.fresh_specs_days,
            "price": self.fresh_price_days,
            "maintenance": self.fresh_maintenance_days,
        }[category]


@lru_cache
def settings() -> Settings:
    return Settings()
