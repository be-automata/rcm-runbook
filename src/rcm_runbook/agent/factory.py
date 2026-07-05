"""Agent assembly: model factory (Claude default, env-switchable) + facilitator agent."""

from __future__ import annotations

from typing import Any

from agno.agent import Agent
from agno.db.sqlite import SqliteDb

from rcm_runbook.agent.instructions_es import INSTRUCTIONS_ES
from rcm_runbook.agent.tools import ALL_TOOLS
from rcm_runbook.config import Settings
from rcm_runbook.models.session import RCMSession


def build_model(cfg: Settings) -> Any:
    if cfg.provider == "anthropic":
        from agno.models.anthropic import Claude

        return Claude(id=cfg.model_id)
    if cfg.provider == "openai":
        from agno.models.openai import OpenAIChat

        return OpenAIChat(id=cfg.model_id)
    if cfg.provider == "google":
        from agno.models.google import Gemini

        return Gemini(id=cfg.model_id)
    raise ValueError(f"Proveedor no soportado: {cfg.provider}")


def build_agent(cfg: Settings, db: SqliteDb | None = None) -> Agent:
    return Agent(
        name="Facilitador RCM",
        model=build_model(cfg),
        db=db or SqliteDb(db_file=cfg.db_path),
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
