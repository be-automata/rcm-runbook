"""El Worker no tenía ni una prueba, y ya fue código muerto una vez.

La primera versión de `estaArrancando` envolvía el fetch en un try/catch que
nunca se disparaba, porque `@cloudflare/containers` no lanza: devuelve un
`Response` con el error en el cuerpo. Parecía correcta y no hacía nada. Lo que
la habría cazado es esto: ejecutar la función real contra respuestas reales.

Como el resto del archivo importa del runtime de Cloudflare, se extrae solo el
trozo que decide —la lista de avisos y `estaArrancando`— y se corre en node.
Si alguien lo renombra o cambia su forma, la extracción falla y el test lo dice,
que es justo lo que queremos que pase.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WORKER = Path(__file__).resolve().parents[2] / "worker" / "index.ts"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node no instalado")


def _fuente_js() -> str:
    """Extrae la lista y la función, y les quita los tipos de TypeScript."""
    texto = WORKER.read_text(encoding="utf-8")
    inicio = texto.index("const AVISOS_DE_LA_LIBRERIA")
    fin = texto.index("function respuestaDeEspera")
    trozo = texto[inicio:fin]
    assert "estaArrancando" in trozo, "cambió la forma del worker; revisa la extracción"
    trozo = trozo.replace("res: Response", "res").replace(": Promise<boolean>", "")
    return trozo.replace("(aviso: string)", "(aviso)")


def _decide(status: int, cuerpo: str) -> bool:
    guion = (
        _fuente_js()
        + f"\nestaArrancando(new Response({json.dumps(cuerpo)}, "
        + f"{{status: {status}}})).then(r => console.log(JSON.stringify(r)));"
    )
    salida = subprocess.run(
        ["node", "--input-type=module", "-e", guion],
        capture_output=True, text=True, timeout=30, check=True,
    )
    return json.loads(salida.stdout.strip())


class TestArranqueEnFrio:
    @pytest.mark.parametrize(
        ("status", "cuerpo"),
        [
            (500, "Error proxying request to container: The container is not running"),
            (500, "Container suddenly disconnected"),
            (500, "Failed to start container"),
            (503, "There is no Container instance available"),
            (520, "Origin is disallowed"),
        ],
    )
    def test_los_cinco_avisos_de_la_libreria_se_reconocen(self, status, cuerpo):
        assert _decide(status, cuerpo) is True, "este error en inglés llegaría al cliente"

    def test_el_429_del_rate_limit_no_necesita_cadena(self):
        # container.js:876 devuelve el mensaje crudo, sin prefijo fijo: filtrar
        # por texto lo dejaba escapar. Un 429 del contenedor es «aún no puedo».
        assert _decide(429, "you are requesting too many containers per second") is True
        assert _decide(429, "cualquier otro texto") is True

    def test_una_respuesta_buena_pasa_de_largo(self):
        assert _decide(200, '{"content":"hola"}') is False

    def test_un_500_de_la_app_no_se_disfraza_de_arranque(self):
        # Si un fallo real de la app se tratara como arranque, el cliente vería
        # «iniciando…» para siempre y nadie se enteraría de que algo se rompió.
        assert _decide(500, "Internal Server Error: ZeroDivisionError") is False


def _fuente_espera() -> str:
    """La página de espera y su selector, listos para ejecutar en node."""
    texto = WORKER.read_text(encoding="utf-8")
    inicio = texto.index("function paginaDespertando")
    fin = texto.index("export default")
    trozo = texto[inicio:fin]
    assert "respuestaDeEspera" in trozo, "cambió la forma del worker"
    return (
        trozo.replace("(): Response", "()")
        .replace("(request: Request): Response", "(request)")
        .replace("res: Response", "res")
        .replace(": Promise<boolean>", "")
    )


class TestLaPaginaDeEspera:
    """El arnés cortaba justo antes de `respuestaDeEspera`, así que el criterio
    28 —«sale la página de espera en español, no un 500 en inglés»— no tenía ni
    un assert."""

    def _responder(self, accept: str) -> dict:
        guion = (
            _fuente_espera()
            + "const r = respuestaDeEspera(new Request('https://x/', "
            + f"{{headers: {{accept: {json.dumps(accept)}}}}}));"
            + "r.text().then(t => console.log(JSON.stringify("
            + "{status: r.status, tipo: r.headers.get('content-type'), cuerpo: t})));"
        )
        salida = subprocess.run(
            ["node", "--input-type=module", "-e", guion],
            capture_output=True, text=True, timeout=30, check=True,
        )
        return json.loads(salida.stdout.strip())

    def test_al_navegador_le_llega_html_en_español(self):
        r = self._responder("text/html,application/xhtml+xml")
        assert r["status"] == 503
        assert "text/html" in r["tipo"]
        assert 'lang="es"' in r["cuerpo"]
        assert "Iniciando el Facilitador RCM" in r["cuerpo"]
        assert "está arrancando" in r["cuerpo"]

    def test_no_se_le_cuela_ni_una_frase_en_inglés(self):
        cuerpo = self._responder("text/html")["cuerpo"]
        for frase in ("container", "Container", "not running", "Error proxying",
                      "starting", "Please wait"):
            assert frase not in cuerpo, f"texto en inglés en la página: {frase}"

    def test_se_recarga_sola_para_que_el_cliente_no_haga_nada(self):
        cuerpo = self._responder("text/html")["cuerpo"]
        assert 'http-equiv="refresh"' in cuerpo

    def test_a_la_api_le_llega_json_no_html(self):
        r = self._responder("application/json")
        assert r["status"] == 503
        assert "application/json" in r["tipo"]
        assert "iniciando" in json.loads(r["cuerpo"])["detail"].lower()


def _fuente_handler() -> str:
    """Todo el worker menos la clase del contenedor, para poder EJECUTAR el
    `fetch` con un contenedor de mentira.

    Los tests que había aquí eran `grep` sobre el fuente, y el validador lo
    demostró: metiendo un `return res;` antes de consultar `estaArrancando`, el
    selector quedaba como código muerto —la regresión exacta que este archivo
    dice prevenir— y los 15 tests seguían en verde. Fijaban texto donde tenían
    que fijar comportamiento.
    """
    texto = WORKER.read_text(encoding="utf-8")
    inicio = texto.index("function paginaDespertando")
    trozo = texto[inicio:]
    trozo = (
        trozo.replace("(): Response", "()")
        .replace("(request: Request): Response", "(request)")
        .replace("res: Response", "res")
        .replace(": Promise<boolean>", "")
        .replace("(aviso: string)", "(aviso)")
        .replace("async fetch(request: Request, env: Env): Promise<Response>",
                 "async fetch(request, env)")
        .replace("export default {", "const worker = {")
    )
    assert "const worker = {" in trozo, "cambió la forma del worker"
    # Sin anteponer _fuente_js(): desde `paginaDespertando` hasta el final ya
    # vienen la lista y `estaArrancando`, y declararlas dos veces es un
    # SyntaxError.
    return trozo


def _pasar_por_el_worker(respuestas: list[dict], metodo: str = "GET") -> dict:
    """Ejecuta el `fetch` real contra un contenedor simulado que devuelve, en
    orden, las respuestas dadas. Devuelve lo que ve el cliente."""
    guion = (
        # Los reintentos esperan 1500 ms de verdad; aquí no se espera nada, que
        # lo que se comprueba es la decisión, no el reloj.
        "const _st = globalThis.setTimeout;"
        "globalThis.setTimeout = (fn) => _st(fn, 0);"
        + _fuente_handler()
        + f"const guion = {json.dumps(respuestas)};"
        + "let llamadas = 0;"
        + "globalThis.getContainer = () => ({ fetch: async () => {"
        + "  const r = guion[Math.min(llamadas, guion.length - 1)]; llamadas++;"
        + "  return new Response(r.cuerpo, {status: r.status}); } });"
        + "const env = { RCM_CONTAINER: {} };"
        + f"const req = new Request('https://x/demo', {{method: {json.dumps(metodo)}, "
        + "headers: {accept: 'text/html'}});"
        + "worker.fetch(req, env).then(async (res) => console.log(JSON.stringify("
        + "{status: res.status, cuerpo: await res.text(), llamadas})));"
    )
    salida = subprocess.run(
        ["node", "--input-type=module", "-e", guion],
        capture_output=True, text=True, timeout=30, check=True,
    )
    return json.loads(salida.stdout.strip())


class TestElWorkerEjecutandose:
    """Ahora se ejecuta el `fetch` de verdad contra un contenedor simulado."""

    ARRANCANDO = {"status": 500, "cuerpo": "Error proxying request to container"}
    BUENA = {"status": 200, "cuerpo": '{"content":"hola"}'}

    def test_el_error_en_ingles_nunca_llega_al_cliente(self):
        r = _pasar_por_el_worker([self.ARRANCANDO])
        assert r["status"] == 503
        assert "Error proxying" not in r["cuerpo"]
        assert "Iniciando el Facilitador RCM" in r["cuerpo"]

    def test_una_respuesta_buena_pasa_intacta(self):
        r = _pasar_por_el_worker([self.BUENA])
        assert r["status"] == 200
        assert r["cuerpo"] == '{"content":"hola"}'
        assert r["llamadas"] == 1, "reintentó algo que ya estaba bien"

    def test_reintenta_el_GET_y_devuelve_la_buena(self):
        r = _pasar_por_el_worker([self.ARRANCANDO, self.BUENA])
        assert r["status"] == 200
        assert r["llamadas"] == 2, "no reintentó un GET que sí es idempotente"

    def test_el_POST_no_se_reintenta_nunca(self):
        # Reintentarlo duplicaría el turno del cliente y le cobraría dos veces
        # el modelo.
        r = _pasar_por_el_worker([self.ARRANCANDO, self.BUENA], metodo="POST")
        assert r["llamadas"] == 1, "reintentó un POST: el turno se duplica"
        assert r["status"] == 503

    def test_un_500_de_la_app_llega_tal_cual(self):
        # Si un fallo real se disfrazara de arranque, el cliente vería
        # «iniciando…» para siempre y nadie se enteraría de que algo se rompió.
        r = _pasar_por_el_worker([{"status": 500, "cuerpo": "ZeroDivisionError"}])
        assert r["status"] == 500
        assert "ZeroDivisionError" in r["cuerpo"]

    def test_el_429_del_rate_limit_se_convierte_en_espera(self):
        r = _pasar_por_el_worker(
            [{"status": 429, "cuerpo": "you are requesting too many containers per second"}]
        )
        assert r["status"] == 503
        assert "Iniciando el Facilitador RCM" in r["cuerpo"]


class TestElSelectorEstaCableado:
    """Desconectar `estaArrancando` del `fetch` dejaba 281 tests en verde. Es
    literalmente la regresión que el docstring del archivo dice prevenir: la
    primera versión del arreglo era código muerto y parecía correcta."""

    def test_el_fetch_consulta_estaArrancando(self):
        texto = WORKER.read_text(encoding="utf-8")
        cuerpo = texto[texto.index("export default"):]
        assert "await estaArrancando(res)" in cuerpo, (
            "el selector existe pero nadie lo llama: código muerto"
        )
        assert cuerpo.index("contenedor.fetch(request)") < cuerpo.index("estaArrancando"), (
            "se consulta antes de tener la respuesta"
        )

    def test_lo_que_no_es_arranque_se_devuelve_tal_cual(self):
        cuerpo = WORKER.read_text(encoding="utf-8")
        cuerpo = cuerpo[cuerpo.index("export default"):]
        assert "if (!(await estaArrancando(res))) return res;" in cuerpo

    def test_solo_se_reintenta_lo_idempotente(self):
        # Un POST a /runs reintentado duplicaría el turno del cliente y le
        # cobraría dos veces el modelo.
        cuerpo = WORKER.read_text(encoding="utf-8")
        assert 'request.method === "GET" || request.method === "HEAD"' in cuerpo
