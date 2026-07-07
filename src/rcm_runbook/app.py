"""AgentOS entrypoint — FastAPI runtime + chat UI + export download endpoint.

Run: `uv run rcm-runbook` (or `uvicorn rcm_runbook.app:app`).

Security: when OS_SECURITY_KEY is set (recommended before exposing publicly),
every AgentOS API route requires `Authorization: Bearer <key>` — os.agno.com
asks for this same key when connecting the OS. The /exports download accepts
the bearer header or `?key=<key>` (browser-friendly links from the chat).
"""

from __future__ import annotations

import hmac
import re
from pathlib import Path

from agno.os import AgentOS
from agno.os.settings import AgnoAPISettings
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse

from rcm_runbook.agent.factory import build_agent
from rcm_runbook.config import settings
from rcm_runbook.observability import setup_observability

setup_observability(settings)

if settings.provider == "anthropic" and not settings.claude_code_oauth_token:
    import os as _os

    if not _os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit(
            "✗ Sin credencial Anthropic: defina CLAUDE_CODE_OAUTH_TOKEN (suscripción, "
            "recomendado — `claude setup-token`) o ANTHROPIC_API_KEY en el .env de la "
            "raíz del proyecto, y reinicie. El servidor no arranca sin credencial para "
            "evitar errores en el primer mensaje del chat."
        )

agent = build_agent(settings)
agent_os = AgentOS(
    agents=[agent],
    settings=AgnoAPISettings(os_security_key=settings.os_security_key or None),
)
app = agent_os.get_app()

_SAFE_NAME = re.compile(r"^[\w.\-]+$")


def _check_export_access(request: Request) -> None:
    """Same key as the AgentOS API: bearer header o `?key=` para enlaces de descarga."""
    if not settings.os_security_key:
        return  # sin llave configurada (uso local) — abierto
    header = request.headers.get("Authorization", "")
    supplied = header[7:] if header.lower().startswith("bearer ") else (
        request.query_params.get("key", "")
    )
    if not hmac.compare_digest(supplied, settings.os_security_key):
        raise HTTPException(status_code=401, detail="Llave de acceso inválida o ausente.")


@app.get("/exports/{session_id}/{filename}")
def download_export(session_id: str, filename: str, request: Request) -> FileResponse:
    """Serve a session's deliverable. Path-sanitized: names only, no separators;
    exports are scoped per session directory (no cross-session access/overwrites)."""
    _check_export_access(request)
    if not (_SAFE_NAME.match(session_id) and _SAFE_NAME.match(filename)):
        raise HTTPException(status_code=400, detail="Nombre inválido.")
    if not filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Solo se sirven archivos .xlsx.")
    exports_root = Path(settings.exports_dir).resolve()
    path = (exports_root / session_id / filename).resolve()
    if not path.is_file() or exports_root not in path.parents:
        raise HTTPException(status_code=404, detail="Entregable no encontrado.")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
    )


def main() -> None:
    import uvicorn

    uvicorn.run("rcm_runbook.app:app", host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
