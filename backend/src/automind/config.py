from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]  # repo root (carexepert/)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(ROOT / ".env", ROOT / "backend" / ".env"), extra="ignore")

    database_url: str = f"postgresql+asyncpg://postgres@/automind?host={ROOT}/.pgdata/pg"

    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    tavily_api_key: str | None = None

    # Per-turn limits (FR-041). Models per role live in config/models.yaml (constitution VII).
    max_llm_calls_per_turn: int = 80
    cost_confirm_threshold_eur: float = 0.30
    cost_hard_cap_eur: float = 1.00
    max_concurrency: int = 4
    job_timeout_s: float = 90.0
    turn_timeout_s: float = 300.0
    max_docs_per_car: int = 8
    max_doc_chars: int = 14000
    request_timeout_s: int = 30
    extraction_concurrency: int = 4

    # cache freshness per category (days)
    fresh_specs_days: int = 365
    fresh_price_days: int = 30
    fresh_maintenance_days: int = 365

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
