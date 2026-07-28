"""Ejecuta el JS real de la página de demo en node, con un DOM mínimo.

Los tests de `test_demo_page.py` comprueban que ciertas cadenas están en el HTML.
Aquí se ejecuta el script tal cual sale de `demo.html` y se afirma sobre el
resultado — id resuelto, URL reescrita, historial pintado —, que es la promesa
real del producto: no perder el análisis al recargar ni al cambiar de
dispositivo. Este arnés ya cazó un salto de línea que rompía el script entero.

La configuración viaja por variable de entorno, no por reemplazo de cadenas: un
placeholder podría colisionar con el propio JS de la página y corromperlo en
silencio.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

import pytest

from rcm_runbook.demo_page import DEMO_HTML

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node no disponible")

_SCRIPT = re.search(r"<script>(.*?)</script>", DEMO_HTML, re.S).group(1)

_PRELUDIO = """
const CFG = JSON.parse(process.env.CFG);
const resultado = { fetches: [], burbujas: [], avisos: [], alertas: [] };

function el(id) {
  return {
    id, value: '', disabled: false, style: {}, textContent: '', className: '',
    scrollHeight: 0, scrollTop: 0, children: [],
    addEventListener(ev, fn) { (this._h ||= {})[ev] = fn; },
    appendChild(n) { this.children.push(n); },
    remove() { this._quitado = true; }, focus() {}, requestSubmit() {},
  };
}
const elementos = {};
for (const id of ['log', 'inp', 'send', 'f', 'hint', 'nuevo']) elementos[id] = el(id);
elementos.log.appendChild = function (n) {
  // El fragmento llega con hijos; se aplana como haría el DOM real.
  for (const hijo of (n.children && n.children.length ? n.children : [n])) {
    (hijo.className || '').startsWith('msg ')
      ? resultado.burbujas.push(hijo.className.slice(4) + '|' + hijo.textContent)
      : resultado.avisos.push(hijo.textContent);
  }
};

global.document = {
  getElementById: (id) => elementos[id] || null,
  createElement: () => el('nodo'),
  createDocumentFragment: () => el('fragmento'),
};
global.localStorage = {
  _d: new Map(CFG.store),
  getItem(k) { if (CFG.bloquea) throw new Error('privado');
    return this._d.has(k) ? this._d.get(k) : null; },
  setItem(k, v) { if (CFG.bloquea) throw new Error('privado'); this._d.set(k, v); },
  removeItem(k) { if (CFG.bloquea) throw new Error('privado'); this._d.delete(k); },
};
global.location = {
  pathname: '/demo', search: CFG.busqueda,
  replace(u) { resultado.replace = u; },
};
global.history = { replaceState(_a, _b, url) { resultado.urlFinal = url; } };
global.confirm = (m) => { resultado.alertas.push(m); return CFG.confirma; };
global.fetch = async (url, opts) => {
  resultado.fetches.push(url);
  resultado.cabeceras = opts && opts.headers;
  resultado.sendDurante = elementos.send.disabled;
  return { ok: CFG.estado === 200, status: CFG.estado, json: async () => CFG.runs };
};
global.console = { warn() {}, log() {} };
"""

_EPILOGO = """
(async () => {
  await new Promise((r) => setTimeout(r, 0));
  resultado.sessionGuardado = localStorage._d.get('rcm-demo-session') ?? null;
  resultado.sendDeshabilitado = elementos.send.disabled;
  if (CFG.pulsaNuevo && elementos.nuevo._h?.click) {
    elementos.nuevo._h.click();
    resultado.sessionTrasNuevo = localStorage._d.get('rcm-demo-session') ?? null;
    resultado.previaTrasNuevo = localStorage._d.get('rcm-demo-session-previa') ?? null;
  }
  process.stdout.write(JSON.stringify(resultado));
})();
"""


def correr(**cfg) -> dict:
    cfg = {
        "busqueda": "?key=abc", "store": [], "estado": 404, "runs": [],
        "pulsaNuevo": False, "confirma": True, "bloquea": False,
    } | cfg
    if isinstance(cfg["store"], dict):
        cfg["store"] = list(cfg["store"].items())
    out = subprocess.run(
        ["node", "--input-type=module", "-e", _PRELUDIO + _SCRIPT + _EPILOGO],
        capture_output=True, text=True, timeout=30,
        env={**os.environ, "CFG": json.dumps(cfg)},
    )
    assert out.returncode == 0, out.stderr[-1500:]
    return json.loads(out.stdout)


class TestResolucionDeSesion:
    def test_sin_nada_previo_crea_id_y_lo_pone_en_la_url(self):
        r = correr()
        assert r["sessionGuardado"].startswith("demo-")
        assert "session=" + r["sessionGuardado"] in r["urlFinal"]
        assert r["fetches"] == []  # sesión nueva: no se pide historial

    def test_id_guardado_se_reutiliza_al_volver_con_el_enlace_simple(self):
        # El caso real: el cliente vuelve a tocar el enlace de WhatsApp, que
        # nunca trae &session=.
        r = correr(store={"rcm-demo-session": "demo-anterior"})
        assert r["sessionGuardado"] == "demo-anterior"
        assert r["fetches"] == ["/sessions/demo-anterior/runs"]

    def test_la_url_gana_sobre_lo_guardado(self):
        # Cambio de dispositivo: la URL copiada manda.
        r = correr(busqueda="?key=abc&session=demo-delotro",
                   store={"rcm-demo-session": "demo-mio"})
        assert r["sessionGuardado"] == "demo-delotro"
        assert r["fetches"] == ["/sessions/demo-delotro/runs"]

    @pytest.mark.parametrize(
        "malicioso", ["../../etc/passwd", "a" * 80, "con espacio", "punto.punto", ""]
    )
    def test_id_invalido_en_la_url_se_descarta(self, malicioso):
        from urllib.parse import quote

        r = correr(busqueda=f"?key=abc&session={quote(malicioso)}",
                   store={"rcm-demo-session": "demo-bueno"})
        assert r["sessionGuardado"] == "demo-bueno"
        assert r["fetches"] == ["/sessions/demo-bueno/runs"], "usó el id de la URL"

    def test_id_nuevo_es_impredecible(self):
        # Con una sola llave compartida, un id corto y adivinable deja leer el
        # análisis de otro.
        ids = {correr()["sessionGuardado"] for _ in range(3)}
        assert len(ids) == 3
        assert all(len(i) > 20 for i in ids), ids


_RUNS = [
    {"status": "COMPLETED", "run_input": "Hola, la bomba P200",
     "content": "Perfecto, registremos."},
    {"status": "ERROR", "run_input": "esto falló", "content": "no debería pintarse"},
    {"status": "COMPLETED", "run_input": "sigue", "content": {"raro": "dict"}},
]


@pytest.fixture(scope="module")
def reanudada():
    """Una sola corrida de node; los tests de abajo miran campos distintos."""
    return correr(busqueda="?key=abc&session=demo-previa", estado=200, runs=_RUNS)


class TestHistorial:
    def test_pide_el_historial_autenticado(self, reanudada):
        assert reanudada["fetches"] == ["/sessions/demo-previa/runs"]
        assert reanudada["cabeceras"] == {"Authorization": "Bearer abc"}

    def test_repinta_la_conversacion_previa(self, reanudada):
        assert "user|Hola, la bomba P200" in reanudada["burbujas"]
        assert "bot|Perfecto, registremos." in reanudada["burbujas"]

    def test_no_repinta_runs_con_error_ni_contenido_no_textual(self, reanudada):
        pintado = "\n".join(reanudada["burbujas"])
        assert "no debería pintarse" not in pintado  # run con status ERROR
        assert "[object Object]" not in pintado  # content que no es str
        assert "raro" not in pintado

    def test_bloquea_el_envio_mientras_carga_y_lo_libera_al_terminar(self, reanudada):
        # Si no, en red lenta el usuario escribe primero y su mensaje queda
        # sepultado bajo la conversación vieja.
        assert reanudada["sendDurante"] is True
        assert reanudada["sendDeshabilitado"] is False

    def test_avisa_cuando_no_hay_analisis_anterior(self):
        r = correr(busqueda="?key=abc&session=demo-fantasma", estado=404)
        assert any("No encontramos un análisis anterior" in a for a in r["avisos"])

    def test_avisa_cuando_la_llave_no_sirve(self):
        r = correr(busqueda="?key=mala&session=demo-previa", estado=401)
        assert any("llave del enlace no es válida" in a for a in r["avisos"])

    def test_sin_llave_no_pide_historial_y_deshabilita_el_envio(self):
        r = correr(busqueda="?session=demo-previa")
        assert r["fetches"] == []
        assert r["sendDeshabilitado"] is True


class TestNuevoAnalisis:
    def test_confirma_antes_de_descartar(self):
        r = correr(store={"rcm-demo-session": "demo-viejo"}, pulsaNuevo=True, confirma=False)
        assert r["alertas"], "no preguntó nada antes de descartar"
        assert r["sessionTrasNuevo"] == "demo-viejo"  # se canceló: no se tocó

    def test_al_confirmar_guarda_el_anterior_y_limpia(self):
        r = correr(store={"rcm-demo-session": "demo-viejo"}, pulsaNuevo=True, confirma=True)
        assert r["sessionTrasNuevo"] is None
        assert r["previaTrasNuevo"] == "demo-viejo"

    def test_usa_replace_para_que_atras_no_resucite_la_sesion(self):
        # Con location.search normal, Atrás devuelve ?session=<viejo>, que tiene
        # precedencia, y el "análisis nuevo" se deshace solo.
        r = correr(store={"rcm-demo-session": "demo-viejo"}, pulsaNuevo=True)
        assert "session=" not in r["replace"]

    def test_ofrece_volver_al_analisis_descartado(self):
        # El id descartado se guardaba y nadie lo leía: un toque de más dejaba
        # el análisis anterior inalcanzable desde la pantalla.
        r = correr(store={"rcm-demo-session-previa": "demo-descartado"})
        assert any("análisis anterior guardado" in a for a in r["avisos"])


class TestNavegadorSinAlmacenamiento:
    def test_modo_privado_no_rompe_la_pagina(self):
        r = correr(bloquea=True)
        assert r["urlFinal"], "la página debe seguir funcionando sin localStorage"
        assert any("no guarda la sesión" in a for a in r["avisos"])
