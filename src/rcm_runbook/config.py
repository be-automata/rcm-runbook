"""Application settings — env-driven, RCM_ prefix. Claude by default, provider switchable."""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RCM_", env_file=".env", extra="ignore")

    provider: Literal["anthropic", "openai", "google"] = "anthropic"
    model_id: str = "claude-sonnet-4-5"
    db_path: str = "data/rcm_runbook.db"
    exports_dir: str = "data/exports"
    log_level: str = "INFO"
    otel_enabled: bool = False
    debug_mode: bool = False
    # Long-session history policy (facilitated interviews run hundreds of turns)
    num_history_runs: int = 10
    # Bind localhost by default — no auth layer in the MVP; expose deliberately
    # (RCM_HOST=0.0.0.0) only behind a reverse proxy that authenticates.
    host: str = "127.0.0.1"
    port: int = 7777


settings = Settings()
