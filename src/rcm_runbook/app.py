"""AgentOS entrypoint — FastAPI runtime + chat UI + export download endpoint.

Run: `uv run rcm-runbook` (or `uvicorn rcm_runbook.app:app`).

Security: when OS_SECURITY_KEY is set (recommended before exposing publicly),
every AgentOS API route requires `Authorization: Bearer <key>` — os.agno.com
asks for this same key when connecting the OS. The /exports download accepts
the bearer header or `?key=<key>` (browser-friendly links from the chat).
"""

from __future__ import annotations

import hmac
import json
import logging
import re
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from agno.os import AgentOS
from agno.os.settings import AgnoAPISettings
from fastapi import HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.background import BackgroundTask

from rcm_runbook.agent.factory import build_agent, sondear_modelo
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

# Excluye nombres compuestos solo de puntos («.», «..»), que \w deja pasar.
_SAFE_NAME = re.compile(r"^(?!\.+$)[\w.\-]+$")

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
# Cuidado al desplegar: si `OS_SECURITY_KEY` acaba en el entorno del proceso,
# ese `AgnoAPISettings()` por defecto sí la ve, activa la dependencia de agno y
# entonces solo se acepta `Authorization: Bearer` — los enlaces con `?key=`
# empiezan a dar 401 en las rutas de agno y producción deja de parecerse a
# local. Por eso el contenedor recibe la llave como `RCM_OS_SECURITY_KEY`
# (config.py acepta ambos nombres).
#
# `/favicon.ico` entra porque Safari lo pide aunque el icono vaya embebido, y un
# 401 ahí deja un error rojo en la consola del cliente en cada carga.
_PUBLIC_PATHS = frozenset({"/demo", "/health", "/favicon.ico"})

logger = logging.getLogger(__name__)

# Orígenes que AgentOS ya autoriza por CORS. Sin esto, nuestro 401 sale sin
# cabeceras CORS (envolvemos al CORSMiddleware) y os.agno.com muestra un error
# opaco de CORS en vez del mensaje en español.
# `cast` porque los tipos de Starlette declaran `cls` y `kwargs` de forma que
# mypy no puede seguir; el acceso es correcto en tiempo de ejecución.
_CORS_ORIGINS = frozenset(
    o
    for m in cast("list[Any]", app.user_middleware)
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

_FAVICON_SVG = (
    b"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>"
    b"<rect width='32' height='32' rx='7' fill='#1F4E78'/>"
    b"<text x='16' y='23' font-size='18' font-family='Helvetica,Arial'"
    b" font-weight='bold' fill='white' text-anchor='middle'>R</text></svg>"
)


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


# Los fallos del proveedor del modelo NO llegan como error HTTP: llegan con 200
# y el texto en inglés dentro del `content` del turno, con el estado de
# facturación del operador dentro. Se vio literal en producción:
# «Your credit balance is too low… Please go to Plans & Billing to upgrade».
#
# Estaba traducido en el navegador, en `demo.html`. Eso deja fuera a todo el que
# no use esa página —la UI de os.agno.com, cualquier cliente de la API—, que es
# la mitad de los caminos y justo la que un integrador ve primero. La capa que
# traduce errores envuelve las llamadas a herramientas, no la del modelo, así
# que el único fallo que estaba ocurriendo era precisamente el que no cubría.
# Se reconoce PRIMERO la envoltura del error y solo después se clasifica. Al
# revés —buscando «overloaded», «rate limit» o «529» sueltos— el traductor se
# comía respuestas legítimas del Facilitador: «la presión de diseño es 529 kPa»,
# «el MTBF del sello es de 529 horas», «el modo es "motor overloaded" según ISO
# 14224», «el PLC aplica un rate-limit a la señal». 10 de 12 respuestas técnicas
# realistas se convertían en un aviso de avería, y como aquí se SUSTITUYE el
# contenido, el análisis del cliente desaparecía antes de salir del servidor.
# «overloaded» es vocabulario de modo de falla en este mismo producto.
_ENVOLTURA_DEL_PROVEEDOR = re.compile(
    # «Error code: NNN» es el prefijo que pone el SDK, y `"type": "error"` es la
    # forma del cuerpo. Los DOS son de la API del proveedor.
    #
    # `\w+_error` a secas NO vale, aunque lo pareciera: `human_error`,
    # `operator_error`, `common_cause_error`, `design_error` son vocabulario
    # literal de FMEA, y los nombres de campo de un CMMS también. 10 de 10
    # respuestas legítimas que los mencionaban se sustituían por un aviso de
    # avería. Es el defecto de la ronda 27 por la puerta de al lado: cambié una
    # lista de palabras sueltas por un patrón que las abarca todas.
    r"""Error code:\s*\d+|['"]type['"]\s*:\s*['"]error['"]""",
    re.I,
)

_FALLOS_DEL_PROVEEDOR: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"credit balance is too low|billing", re.I),
     "El servicio no está disponible en este momento por un problema de la "
     "cuenta del sistema. Avise a quien le compartió este enlace; su análisis "
     "queda guardado y puede retomarlo después."),
    (re.compile(r"rate_limit_error|too many requests", re.I),
     "El sistema está recibiendo muchas consultas a la vez. Espere unos "
     "segundos y vuelva a enviar su mensaje."),
    (re.compile(r"overloaded_error", re.I),
     "El servicio está saturado en este momento. Espere unos segundos y vuelva "
     "a intentarlo."),
    (re.compile(r"authentication_error|permission_error|invalid x-api-key", re.I),
     "El servicio no está disponible por un problema de configuración del "
     "sistema. Avise a quien le compartió este enlace."),
)

# Un error del proveedor que no reconozco sigue siendo un error del proveedor:
# dejarlo pasar en inglés era el defecto original.
_FALLO_GENERICO = (
    "El sistema tuvo un fallo técnico al procesar su mensaje. Avise a quien le "
    "compartió este enlace; su análisis queda guardado."
)


def en_espanol_si_es_fallo_del_proveedor(texto: str) -> str:
    """El texto del turno, con el fallo del proveedor traducido y sin facturación.

    Devuelve el original si no reconoce ningún fallo: traducir de más
    convertiría una respuesta legítima del agente en un aviso de avería.
    """
    if not isinstance(texto, str) or not _ENVOLTURA_DEL_PROVEEDOR.search(texto):
        return texto
    # Sin adjuntar el original: lleva dentro el estado de facturación del
    # operador, que no es asunto del cliente.
    logger.warning("fallo del proveedor servido al cliente: %s", texto[:200])
    for patron, en_espanol in _FALLOS_DEL_PROVEEDOR:
        if patron.search(texto):
            return en_espanol
    return _FALLO_GENERICO


class TraducirFallosDelProveedor:
    """Traduce el fallo del proveedor antes de que salga del servidor.

    ASGI puro y solo sobre respuestas JSON no-transmitidas, por lo mismo que
    `RequireKey`: bufferizar el streaming de runs rompe el backpressure que
    consume la UI de os.agno.com. Lo que va por SSE no se toca —queda
    documentado como descubierto, no como resuelto—; el chat de `/demo` pide
    `stream=false`, así que ese camino sí queda cubierto en el servidor además
    de en el navegador.
    """

    def __init__(self, app: Callable) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http" or "/runs" not in scope.get("path", ""):
            await self.app(scope, receive, send)
            return

        inicio: dict[str, Any] = {}
        trozos: list[bytes] = []
        es_json = False

        async def interceptar(mensaje: dict) -> None:
            nonlocal es_json
            if mensaje["type"] == "http.response.start":
                cabeceras = {k.decode().lower(): v.decode() for k, v in mensaje["headers"]}
                es_json = cabeceras.get("content-type", "").startswith("application/json")
                if not es_json:
                    await send(mensaje)
                    return
                inicio.update(mensaje)
                return
            if mensaje["type"] == "http.response.body" and es_json:
                trozos.append(mensaje.get("body", b""))
                if mensaje.get("more_body"):
                    return
                await _enviar_traducido(send, inicio, b"".join(trozos))
                return
            await send(mensaje)

        await self.app(scope, receive, interceptar)


def _traducir_contenidos(datos: Any) -> Any:
    """Recorre el JSON entero traduciendo cada `content` que sea un fallo.

    Mirar solo la raíz cuando era un `dict` dejaba fuera el historial:
    `/sessions/{id}/runs` devuelve una LISTA de turnos, así que el turno con el
    error se servía tal cual y la facturación del operador salía en claro cada
    vez que alguien recargaba la conversación. La traducción había subido al
    servidor para el turno vivo y se había quedado abajo para el historial —una
    promesa a medias es peor que no haberla hecho, porque nadie vuelve a mirar.
    """
    if isinstance(datos, list):
        return [_traducir_contenidos(x) for x in datos]
    if not isinstance(datos, dict):
        return datos
    salida = {k: _traducir_contenidos(v) for k, v in datos.items()}
    # SOLO lo que dijo el asistente. Recorrer todo `content` sin mirar de quién
    # es aplicaba a la entrada del cliente una regla pensada para la salida del
    # modelo: se observó en producción la pregunta que escribió el usuario
    # —«el modo dominante es human_error durante el arranque»— sustituida por
    # «el sistema tuvo un fallo técnico», un aviso que además miente, y visible
    # cada vez que alguien recargaba la conversación. Ese texto no lo escribió
    # el proveedor; por buena que sea la detección, traducirlo nunca es
    # correcto. El prompt de sistema se salvaba por suerte, no por diseño.
    papel = salida.get("role")
    if papel in (None, "assistant", "model") and isinstance(salida.get("content"), str):
        salida["content"] = en_espanol_si_es_fallo_del_proveedor(salida["content"])
    return salida


async def _enviar_traducido(send: Callable, inicio: dict, cuerpo: bytes) -> None:
    """Reescribe `content` si trae un fallo del proveedor y reenvía la respuesta.

    Cualquier tropiezo deja pasar el original: un traductor que rompe la
    respuesta es peor que uno que no traduce.
    """
    nuevo = cuerpo
    try:
        datos = json.loads(cuerpo)
        traducido = _traducir_contenidos(datos)
        if traducido != datos:
            nuevo = json.dumps(traducido, ensure_ascii=False).encode()
    except (ValueError, TypeError, RecursionError):  # pragma: no cover
        # `RecursionError` faltaba y el docstring prometía que cualquier
        # tropiezo deja pasar el original: sin capturarla, un JSON muy anidado
        # reventaba DESPUÉS de haber retenido la cabecera, o sea sin respuesta.
        nuevo = cuerpo
    cabeceras = [
        (k, v) for k, v in inicio["headers"] if k.decode().lower() != "content-length"
    ]
    cabeceras.append((b"content-length", str(len(nuevo)).encode()))
    await send({**inicio, "headers": cabeceras})
    await send({"type": "http.response.body", "body": nuevo, "more_body": False})


# El orden importa: `add_middleware` apila, así que el último añadido envuelve
# por fuera. La llave se comprueba primero; traducir la respuesta de quien no
# está autorizado no tendría sentido.
app.add_middleware(TraducirFallosDelProveedor)
app.add_middleware(RequireKey)


def _sesion_guardada(session_id: str):
    """El estado RCM de una sesión, tal como quedó en la base de datos.

    El entregable es función pura de este estado, así que no hace falta
    conservarlo en disco. Es lo que lo hace sobrevivir a un contenedor con disco
    efímero: el archivo que el cliente descarga mañana se genera en el momento.
    """
    from rcm_runbook.models.session import RCMSession

    # `cast` a dict: `get_session` declara una unión que incluye la variante
    # asíncrona y los modelos de sesión de agno, pero con `deserialize=False` y
    # el cliente síncrono devuelve el diccionario crudo.
    db = agent.db
    if db is None:
        return None
    registro = cast(
        "dict[str, Any] | None",
        db.get_session(session_id=session_id, deserialize=False),
    )
    if not registro:
        return None
    estado = (registro.get("session_data") or {}).get("session_state") or {}
    crudo = estado.get("rcm")
    return RCMSession.model_validate(crudo) if crudo else None


@app.get("/exports/{session_id}")
def download_current_export(session_id: str, request: Request) -> FileResponse:
    """Entregable actual de la sesión, sin que el cliente sepa cómo se llama.

    Es lo que usa el botón «Descargar Excel» de la página: el navegador no
    conoce el TAG del equipo, así que el nombre lo resuelve el servidor.

    Entrega el definitivo solo si el análisis pasa las compuertas; si no, un
    BORRADOR_ claramente marcado. Nunca un borrador disfrazado de definitivo.
    """
    from rcm_runbook.engine import compliance
    from rcm_runbook.export.excel import export_xlsx

    if not _SAFE_NAME.match(session_id):
        raise HTTPException(status_code=400, detail="Nombre inválido.")
    sesion = _sesion_guardada(session_id)
    if sesion is None or not sesion.scope.tag:
        raise HTTPException(
            status_code=404,
            detail=(
                "Todavía no hay nada que exportar: primero registre el equipo "
                "y su TAG con el facilitador."
            ),
        )
    borrador = bool(compliance.export_blockers(sesion))
    destino = Path(tempfile.mkdtemp(prefix="rcm-export-"))
    generado = export_xlsx(sesion, destino, session_id=session_id, draft=borrador)
    return _servir(generado, generado.name, temporal=destino)


def _servir(path: Path, filename: str, temporal: Path | None) -> FileResponse:
    """Entrega el .xlsx y borra su directorio temporal cuando toca.

    Cada regeneración crea un `mkdtemp`; sin limpiarlo, cada clic en «Descargar
    Excel» dejaba ~11 KB permanentes en el disco del contenedor.
    """
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
        background=(
            BackgroundTask(shutil.rmtree, temporal, ignore_errors=True)
            if temporal
            else None
        ),
    )


def _regenerar_entregable(session_id: str, filename: str) -> Path | None:
    """Reconstruye el .xlsx pedido por nombre exacto, desde la base de datos."""
    from rcm_runbook.engine import compliance
    from rcm_runbook.export.excel import export_xlsx

    sesion = _sesion_guardada(session_id)
    if sesion is None:
        return None
    borrador = filename.startswith("BORRADOR_")
    # Misma compuerta que aplica la herramienta `export_excel`: sin esto bastaba
    # quitar el prefijo BORRADOR_ de la URL para llevarse un "entregable
    # definitivo" de un análisis a medias, que es justo lo que la norma prohíbe.
    if not borrador and compliance.export_blockers(sesion):
        return None
    destino = Path(tempfile.mkdtemp(prefix="rcm-export-"))
    generado = export_xlsx(sesion, destino, session_id=session_id, draft=borrador)
    return generado if generado.name == filename else None


@app.get("/exports/{session_id}/{filename}")
def download_export(session_id: str, filename: str, request: Request) -> FileResponse:
    """Serve a session's deliverable. Path-sanitized: names only, no separators;
    exports are scoped per session directory (no cross-session access/overwrites).

    Se busca primero en disco (la exportación recién hecha) y, si no está, se
    regenera desde la base de datos — el despliegue en la nube no tiene disco
    que sobreviva a un reinicio.

    La llave ya la exigió `require_key`: `/exports/...` no está en la lista blanca."""
    from rcm_runbook.engine import compliance

    if not (_SAFE_NAME.match(session_id) and _SAFE_NAME.match(filename)):
        raise HTTPException(status_code=400, detail="Nombre inválido.")
    if not filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Solo se sirven archivos .xlsx.")
    # La compuerta se evalúa ANTES de mirar el disco. Si no, un definitivo
    # exportado cuando la sesión estaba completa se seguiría sirviendo después de
    # que el análisis retrocediera de fase: el archivo en disco es una foto vieja,
    # el estado de la sesión es la verdad.
    if not filename.startswith("BORRADOR_"):
        sesion = _sesion_guardada(session_id)
        if sesion is None or compliance.export_blockers(sesion):
            raise HTTPException(status_code=404, detail="Entregable no encontrado.")
    exports_root = Path(settings.exports_dir).resolve()
    path = (exports_root / session_id / filename).resolve()
    if path.is_file() and exports_root in path.parents:
        return _servir(path, filename, temporal=None)
    generado = _regenerar_entregable(session_id, filename)
    if generado is None:
        raise HTTPException(status_code=404, detail="Entregable no encontrado.")
    return _servir(generado, filename, temporal=generado.parent.parent)


@app.get("/health/modelo")
def health_modelo() -> JSONResponse:
    """Sonda profunda: ¿puede el sistema atender un turno de verdad?

    Va detrás de la llave a propósito (no está en _PUBLIC_PATHS): gasta un token
    del operador, y una sonda pública sería una forma cómoda de vaciarle la
    cuenta a alguien recargando una URL.

    `/health` sigue siendo la sonda barata para saber si el proceso vive. Esta es
    la que hay que vigilar para enterarse de una caída como la del saldo, que
    dejó el producto muerto con la otra en verde.
    """
    ok, detalle = sondear_modelo(settings)
    return JSONResponse(
        {"estado": "ok" if ok else "degradado", "detalle": detalle},
        status_code=200 if ok else 503,
    )


@app.get("/favicon.ico")
def favicon() -> Response:
    """El icono va embebido en la página, pero algunos navegadores lo piden igual.
    Servirlo evita un 404 en la consola del cliente."""
    return Response(content=_FAVICON_SVG, media_type="image/svg+xml")


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
