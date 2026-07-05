"""Application settings — env-driven, RCM_ prefix. Claude by default, provider switchable."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# .env resolves against the project root too, not only the launch cwd —
# `uv run rcm-runbook` must work from any directory.
_PROJECT_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RCM_",
        env_file=(str(_PROJECT_ROOT_ENV), ".env"),
        extra="ignore",
        populate_by_name=True,
    )

    provider: Literal["anthropic", "openai", "google"] = "anthropic"
    model_id: str = "claude-sonnet-4-5"
    # Claude subscription auth (OAuth token from `claude setup-token`).
    # When set, the Anthropic SDK authenticates with `Authorization: Bearer` +
    # the `anthropic-beta: oauth-2025-04-20` header instead of an API key —
    # usage bills to the Claude subscription, not pay-per-token credits.
    claude_code_oauth_token: str = Field(
        default="",
        validation_alias=AliasChoices(
            "CLAUDE_CODE_OAUTH_TOKEN", "RCM_CLAUDE_CODE_OAUTH_TOKEN"
        ),
    )
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
