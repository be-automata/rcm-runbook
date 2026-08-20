"""Agent assembly: model factory (Claude default, env-switchable) + facilitator agent.

Anthropic auth resolves in this order:
1. `CLAUDE_CODE_OAUTH_TOKEN` (Claude subscription — `claude setup-token`): bearer auth
   + oauth beta header; any ANTHROPIC_API_KEY is dropped for the process.
2. `ANTHROPIC_API_KEY` (pay-per-token credits): the SDK default.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from agno.agent import Agent
from agno.db.sqlite import SqliteDb

from rcm_runbook.agent.instructions_es import INSTRUCTIONS_ES
from rcm_runbook.agent.tools import ALL_TOOLS
from rcm_runbook.config import Settings
from rcm_runbook.models.session import RCMSession

OAUTH_BETA_HEADER = {"anthropic-beta": "oauth-2025-04-20"}


def sondear_modelo(cfg: Settings) -> tuple[bool, str]:
    """¿Responde de verdad el proveedor del modelo? (ok, detalle en español).

    `/health` mira que el proceso esté vivo y devolvía 200 mientras el producto
    estaba completamente muerto: la cuenta del proveedor se quedó sin crédito y
    cada turno del chat devolvía un error, con la vigilancia en verde. Un
    servicio cuya única sonda no puede distinguir «funciona» de «no funciona»
    no es observable, por muchos 200 que devuelva.

    Cuesta un token y va detrás de la llave: sin eso, cualquiera puede gastar la
    cuenta del operador recargando una URL.
    """
    if cfg.provider != "anthropic":
        return True, f"Proveedor '{cfg.provider}': sondeo no implementado."
    try:
        from anthropic import Anthropic as AnthropicClient

        if cfg.claude_code_oauth_token:
            cliente = AnthropicClient(
                auth_token=cfg.claude_code_oauth_token, default_headers=OAUTH_BETA_HEADER
            )
        else:
            cliente = AnthropicClient()
        cliente.messages.create(
            model=cfg.model_id, max_tokens=1, messages=[{"role": "user", "content": "ok"}]
        )
    except Exception as exc:  # noqa: BLE001 — la sonda informa, no revienta
        detalle = str(exc)
        if "credit balance" in detalle:
            return False, "La cuenta del proveedor del modelo no tiene saldo."
        if "authentication" in detalle.lower() or "api key" in detalle.lower():
            return False, "Las credenciales del proveedor del modelo no son válidas."
        if "rate" in detalle.lower() and "limit" in detalle.lower():
            return False, "El proveedor del modelo está limitando el ritmo de peticiones."
        logger.warning("sondeo del modelo falló: %s", detalle[:200])
        return False, "El proveedor del modelo no respondió correctamente."
    return True, "El proveedor del modelo responde."


def build_model(cfg: Settings) -> Any:
    # `temperature=None` significa "el default del proveedor", que no es lo mismo
    # que 0: se omite el parámetro en vez de mandarlo. Sólo los evals lo fijan.
    muestreo: dict[str, Any] = (
        {} if cfg.temperature is None else {"temperature": cfg.temperature}
    )
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
                **muestreo,
            )
        return Claude(id=cfg.model_id, **muestreo)
    if cfg.provider == "openai":
        from agno.models.openai import OpenAIChat

        return OpenAIChat(id=cfg.model_id, **muestreo)
    if cfg.provider == "google":
        from agno.models.google import Gemini

        return Gemini(id=cfg.model_id, **muestreo)
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


logger = logging.getLogger("rcm_runbook.factory")


def _digest_de_la_sesion(session_state: dict[str, Any] | None = None) -> str:
    """Resumen compacto del análisis, inyectado en el contexto de cada turno.

    Es lo que `get_progress` devuelve, sin depender de que el modelo se acuerde
    de pedirlo. Si algo falla al leer el estado se devuelve un aviso en vez de
    reventar el turno: perder el resumen degrada la conversación, pero perder el
    turno la corta.
    """
    try:
        crudo = (session_state or {}).get("rcm")
        if not crudo:
            return "Análisis nuevo, sin datos registrados todavía."
        return RCMSession.model_validate(crudo).digest_es()
    except Exception:  # noqa: BLE001 — el turno vale más que el resumen
        logger.warning("no se pudo construir el digest de la sesión", exc_info=True)
        return "(No se pudo leer el estado; use get_progress.)"


def build_agent(cfg: Settings, db: Any | None = None) -> Agent:
    return Agent(
        name="Facilitador RCM",
        model=build_model(cfg),
        db=db if db is not None else build_db(cfg),
        tools=list(ALL_TOOLS),
        instructions=INSTRUCTIONS_ES,
        session_state={"rcm": RCMSession().model_dump(mode="json")},
        # El estado completo es demasiado grande para el contexto, pero dejarlo
        # FUERA del todo tenía un coste peor: el agente solo lo veía si llamaba a
        # get_progress, y con una ventana de 10 turnos el dato que el interesado
        # dio y él no registró salía de la historia y desaparecía para siempre.
        # Medido: 31 turnos, 0 modos de falla registrados, el agente repreguntando
        # cosas que él mismo marcaba con «✔ ya lo dijiste». El digest son unas
        # pocas líneas y va en cada turno.
        add_session_state_to_context=False,
        dependencies={"estado_del_analisis": _digest_de_la_sesion},
        add_dependencies_to_context=True,
        add_history_to_context=True,
        num_history_runs=cfg.num_history_runs,
        add_datetime_to_context=cfg.add_datetime,
        markdown=True,
        debug_mode=cfg.debug_mode,
        telemetry=False,
    )
