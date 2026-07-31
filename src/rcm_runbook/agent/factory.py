"""Agent assembly: model factory (Claude default, env-switchable) + facilitator agent.

Anthropic auth resolves in this order:
1. `CLAUDE_CODE_OAUTH_TOKEN` (Claude subscription — `claude setup-token`): bearer auth
   + oauth beta header; any ANTHROPIC_API_KEY is dropped for the process.
2. `ANTHROPIC_API_KEY` (pay-per-token credits): the SDK default.
"""

from __future__ import annotations

import os
from typing import Any

from agno.agent import Agent
from agno.db.sqlite import SqliteDb

from rcm_runbook.agent.instructions_es import INSTRUCTIONS_ES
from rcm_runbook.agent.tools import ALL_TOOLS
from rcm_runbook.config import Settings
from rcm_runbook.models.session import RCMSession

OAUTH_BETA_HEADER = {"anthropic-beta": "oauth-2025-04-20"}


def build_model(cfg: Settings) -> Any:
    if cfg.provider == "anthropic":
        from agno.models.anthropic import Claude

        if cfg.claude_code_oauth_token:
            # Claude subscription auth: OAuth bearer token (from `claude setup-token`).
            # Inject explicit SDK clients so ONLY `Authorization: Bearer` is sent —
            # a lingering ANTHROPIC_API_KEY env var would otherwise be picked up and
            # the API rejects requests carrying both credentials.
            from anthropic import Anthropic as AnthropicClient
            from anthropic import AsyncAnthropic

            os.environ.pop("ANTHROPIC_API_KEY", None)
            client_kwargs: dict[str, Any] = {
                "auth_token": cfg.claude_code_oauth_token,
                "default_headers": OAUTH_BETA_HEADER,
            }
            return Claude(
                id=cfg.model_id,
                auth_token=cfg.claude_code_oauth_token,
                default_headers=OAUTH_BETA_HEADER,
                client=AnthropicClient(**client_kwargs),
                async_client=AsyncAnthropic(**client_kwargs),
            )
        return Claude(id=cfg.model_id)
    if cfg.provider == "openai":
        from agno.models.openai import OpenAIChat

        return OpenAIChat(id=cfg.model_id)
    if cfg.provider == "google":
        from agno.models.google import Gemini

        return Gemini(id=cfg.model_id)
    raise ValueError(f"Proveedor no soportado: {cfg.provider}")


def build_db(cfg: Settings) -> Any:
    """Postgres cuando hay `DATABASE_URL`, SQLite local si no.

    En Cloudflare Containers el disco es efímero: al dormirse el contenedor se
    borra, y con SQLite el cliente perdería su análisis entre una visita y la
    siguiente. Postgres es lo que sostiene la continuidad de sesión en la nube.
    """
    if cfg.db_url:
        from agno.db.postgres import PostgresDb

        return PostgresDb(db_url=cfg.db_url)
    return SqliteDb(db_file=cfg.db_path)


def build_agent(cfg: Settings, db: Any | None = None) -> Agent:
    return Agent(
        name="Facilitador RCM",
        model=build_model(cfg),
        db=db if db is not None else build_db(cfg),
        tools=list(ALL_TOOLS),
        instructions=INSTRUCTIONS_ES,
        session_state={"rcm": RCMSession().model_dump(mode="json")},
        add_session_state_to_context=False,  # digest via get_progress; full state too big
        add_history_to_context=True,
        num_history_runs=cfg.num_history_runs,
        add_datetime_to_context=True,
        markdown=True,
        debug_mode=cfg.debug_mode,
        telemetry=False,
    )
