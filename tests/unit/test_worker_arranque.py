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
