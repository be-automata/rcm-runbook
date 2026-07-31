"""AgentOS entrypoint — FastAPI runtime + chat UI + export download endpoint.

Run: `uv run rcm-runbook` (or `uvicorn rcm_runbook.app:app`).

Security: when OS_SECURITY_KEY is set (recommended before exposing publicly),
every AgentOS API route requires `Authorization: Bearer <key>` — os.agno.com
asks for this same key when connecting the OS. The /exports download accepts
the bearer header or `?key=<key>` (browser-friendly links from the chat).
"""

from __future__ import annotations

import hmac
import logging
import re
import tempfile
from collections.abc import Callable
from pathlib import Path

from agno.os import AgentOS
from agno.os.settings import AgnoAPISettings
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from rcm_runbook.agent.factory import build_agent
from rcm_runbook.config import settings
from rcm_runbook.demo_page import DEMO_HTML
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

# Rutas que responden sin llave. Todo lo demás queda cerrado por defecto.
#
# Por qué hace falta una compuerta propia (agno 2.6.22): sus routers SÍ declaran
# `Depends(get_authentication_dependency(settings))`, pero `AgentOS` los crea sin
# pasarle sus settings — `get_session_router(dbs=self.dbs)` en `agno/os/app.py`
# líneas 462 y 983 —, así que reciben un `AgnoAPISettings()` por defecto, que lee
# la llave del *entorno*. La nuestra vive en el `.env`, sin exportar, de modo que
# `auth.py:92` hace `if not settings.os_security_key: return True` y omite la
# autenticación. Medido: `/sessions` y `/sessions/{id}/runs` devolvían 200 con las
# transcripciones completas a cualquiera con la URL pública. Aparte de eso, agno
# solo acepta `Authorization: Bearer`, y necesitamos `?key=` para los enlaces que
# se abren de un clic en el navegador.
#
# `/favicon.ico` entra porque Safari lo pide aunque el icono vaya embebido, y un
# 401 ahí deja un error rojo en la consola del cliente en cada carga.
_PUBLIC_PATHS = frozenset({"/demo", "/health", "/favicon.ico"})

# Orígenes que AgentOS ya autoriza por CORS. Sin esto, nuestro 401 sale sin
# cabeceras CORS (envolvemos al CORSMiddleware) y os.agno.com muestra un error
# opaco de CORS en vez del mensaje en español.
_CORS_ORIGINS = frozenset(
    o
    for m in app.user_middleware
    if m.cls.__name__ == "CORSMiddleware"
    for o in m.kwargs.get("allow_origins", [])
)


def _key_ok(request: Request) -> bool:
    """Bearer en cabecera o `?key=` para enlaces que se abren en el navegador.

    Compara en bytes: `compare_digest` sobre str revienta con un TypeError si
    llega un carácter no-ASCII, y basta con que el cliente pegue un enlace que
    su teclado alteró para convertir un 401 en un 500 con traceback.
    """
    expected = settings.os_security_key
    if not expected:
        return False  # cerrado por defecto; quien permite el uso local es el middleware
    header = request.headers.get("Authorization", "")
    supplied = header[7:] if header.lower().startswith("bearer ") else (
        request.query_params.get("key", "")
    )
    return hmac.compare_digest(
        supplied.encode("utf-8", "replace"), expected.encode("utf-8")
    )


_SIN_LLAVE = "Llave de acceso inválida o ausente."


class RequireKey:
    """Cierra por defecto: sin llave válida no se responde nada fuera de la lista blanca.

    Middleware ASGI puro a propósito. `@app.middleware("http")` envuelve todo en
    el BaseHTTPMiddleware de Starlette, que por petición levanta un task group y
    relaya la respuesta por colas en memoria: eso añade latencia y rompe el
    backpressure del streaming de runs que consume la UI de os.agno.com. Aquí el
    camino autorizado es un `await self.app(...)` y nada más.

    El preflight CORS real pasa sin llave porque el navegador no le pone cabecera
    Authorization; se exige `Access-Control-Request-Method` para que sea eso y no
    un canal para sondear rutas.

    La ruta se normaliza aquí porque corremos por fuera del TrailingSlashMiddleware
    de agno: sin esto, `/demo/` y `/health/` caen en 401 y el cliente que escribe
    la URL con barra final ve un JSON de error en lugar del chat.

    Los WebSockets pasan sin tocar: agno los autentica dentro del protocolo
    (ver TestWebsocketAuth) y exigir la llave en el handshake rompería os.agno.com.
    """

    def __init__(self, app: Callable) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http" or not settings.os_security_key:
            await self.app(scope, receive, send)
            return
        if (scope.get("path", "").rstrip("/") or "/") in _PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive)
        es_preflight = (
            request.method == "OPTIONS"
            and "access-control-request-method" in request.headers
        )
        if es_preflight or _key_ok(request):
            await self.app(scope, receive, send)
            return
        origin = request.headers.get("Origin", "")
        headers = (
            {
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Credentials": "true",
            }
            if origin in _CORS_ORIGINS
            else None
        )
        respuesta = JSONResponse(
            status_code=401, content={"detail": _SIN_LLAVE}, headers=headers
        )
        await respuesta(scope, receive, send)


app.add_middleware(RequireKey)


def _regenerar_entregable(session_id: str, filename: str) -> Path | None:
    """Reconstruye el .xlsx desde el estado guardado en la base de datos.

    El entregable es función pura del estado de la sesión, así que no hace falta
    conservarlo en disco. Esto es lo que lo hace sobrevivir a un contenedor con
    disco efímero: el archivo que el cliente descarga mañana se genera en el
    momento a partir de lo que hay en la base.
    """
    from rcm_runbook.export.excel import export_xlsx
    from rcm_runbook.models.session import RCMSession

    registro = agent.db.get_session(session_id=session_id, deserialize=False)
    if not registro:
        return None
    estado = (registro.get("session_data") or {}).get("session_state") or {}
    crudo = estado.get("rcm")
    if not crudo:
        return None
    destino = Path(tempfile.mkdtemp(prefix="rcm-export-"))
    generado = export_xlsx(
        RCMSession.model_validate(crudo),
        destino,
        session_id=session_id,
        draft=filename.startswith("BORRADOR_"),
    )
    return generado if generado.name == filename else None


@app.get("/exports/{session_id}/{filename}")
def download_export(session_id: str, filename: str, request: Request) -> FileResponse:
    """Serve a session's deliverable. Path-sanitized: names only, no separators;
    exports are scoped per session directory (no cross-session access/overwrites).

    Se busca primero en disco (la exportación recién hecha) y, si no está, se
    regenera desde la base de datos — el despliegue en la nube no tiene disco
    que sobreviva a un reinicio.

    La llave ya la exigió `require_key`: `/exports/...` no está en la lista blanca."""
    if not (_SAFE_NAME.match(session_id) and _SAFE_NAME.match(filename)):
        raise HTTPException(status_code=400, detail="Nombre inválido.")
    if not filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Solo se sirven archivos .xlsx.")
    exports_root = Path(settings.exports_dir).resolve()
    path = (exports_root / session_id / filename).resolve()
    if not path.is_file() or exports_root not in path.parents:
        path = _regenerar_entregable(session_id, filename)
        if path is None:
            raise HTTPException(status_code=404, detail="Entregable no encontrado.")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
    )


@app.get("/demo", response_class=HTMLResponse)
def demo_chat() -> HTMLResponse:
    """Standalone chat page for stakeholder demos (no os.agno.com account).

    The page carries the key via `?key=` in its own fetch calls to the gated
    agent-run endpoint; the HTML itself holds no secret. Share as
    `https://<tunnel>/demo?key=<OS_SECURITY_KEY>`.
    """
    return HTMLResponse(DEMO_HTML)


class _RedactKey(logging.Filter):
    """Tapa `key=<llave>` en el log de acceso de uvicorn.

    Aceptar la llave por query string es lo que hace que un enlace funcione con
    un solo clic, pero uvicorn registra la URL entera: sin esto la llave queda
    en claro en `~/Library/Logs/rcm-runbook.log`, que no rota.
    """

    _PATTERN = re.compile(r"(key=)[^&\s\"']+")

    def filter(self, record: logging.LogRecord) -> bool:
        # uvicorn.access mete la URL en args, nunca en msg.
        if record.args:
            record.args = tuple(
                self._PATTERN.sub(r"\1<oculta>", a) if isinstance(a, str) else a
                for a in record.args
            )
        return True


# Se instala al importar, no en main(): así también protege el arranque por
# `uvicorn rcm_runbook.app:app`, que no pasa por aquí.
logging.getLogger("uvicorn.access").addFilter(_RedactKey())


def main() -> None:
    import uvicorn

    uvicorn.run("rcm_runbook.app:app", host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
