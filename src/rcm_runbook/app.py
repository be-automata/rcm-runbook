"""AgentOS entrypoint — FastAPI runtime + chat UI + export download endpoint.

Run: `uv run rcm-runbook` (or `uvicorn rcm_runbook.app:app`).
"""

from __future__ import annotations

import re
from pathlib import Path

from agno.os import AgentOS
from fastapi import HTTPException
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
agent_os = AgentOS(agents=[agent])
app = agent_os.get_app()

_SAFE_NAME = re.compile(r"^[\w.\-]+$")


@app.get("/exports/{session_id}/{filename}")
def download_export(session_id: str, filename: str) -> FileResponse:
    """Serve a session's deliverable. Path-sanitized: names only, no separators;
    exports are scoped per session directory (no cross-session access/overwrites)."""
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
