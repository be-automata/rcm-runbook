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

function el(id, tag) {
  return {
    id, tag: tag || id, value: '', disabled: false, style: {}, textContent: '',
    className: '', scrollHeight: 0, scrollTop: 0, children: [],
    addEventListener(ev, fn) { (this._h ||= {})[ev] = fn; },
    appendChild(n) { this.children.push(n); },
    remove() { this._quitado = true; }, focus() {}, requestSubmit() {},
    click() { resultado.descarga = this.download; },
  };
}

// El renderizador de markdown construye hijos en vez de asignar textContent:
// sin serializar el árbol, las aserciones de TestHistorial verían burbujas
// vacías y fallarían en falso. Formato: etiqueta(texto)[hijo,hijo].
function serializa(n) {
  if (n == null) return '';
  if (typeof n === 'string') return n;
  const atributos = ['className', 'href', 'target', 'rel']
    .filter((a) => n[a]).map((a) => `${a}=${n[a]}`).join(',');
  const attr = atributos ? `{${atributos}}` : '';
  const propio = n.textContent || '';
  const hijos = (n.children || []).map(serializa).filter(Boolean);
  const dentro = hijos.length ? `[${hijos.join(',')}]` : '';
  return `${n.tag || 'nodo'}(${propio})${attr}${dentro}`;
}
const elementos = {};
for (const id of ['log', 'inp', 'send', 'f', 'hint', 'nuevo', 'exportar'])
  elementos[id] = el(id);
elementos.log.appendChild = function (n) {
  // El fragmento llega con hijos; se aplana como haría el DOM real.
  const esBurbuja = (x) => (x.className || '').startsWith('msg ');
  for (const hijo of (n.tag === 'fragmento' ? n.children : [n])) {
    if (esBurbuja(hijo)) {
      const cuerpo = hijo.children.length
        ? hijo.children.map(serializa).join('')
        : hijo.textContent;
      resultado.burbujas.push(hijo.className.slice(4) + '|' + cuerpo);
    } else {
      resultado.avisos.push(hijo.textContent);
    }
  }
};

global.document = {
  getElementById: (id) => elementos[id] || null,
  createElement: (tag) => el('nodo', tag),
  // Los nodos de texto se representan como cadenas: serializa() las devuelve
  // tal cual. Sin esto el renderizador revienta y todo cae al fallback de
  // textContent, dando tests en verde que no prueban nada.
  createTextNode: (t) => t,
  createDocumentFragment: () => el('fragmento', 'fragmento'),
  body: el('body'),
};
global.URL = { createObjectURL: () => 'blob:x', revokeObjectURL() {} };
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
  if (url.startsWith('/exports/')) {
    return {
      ok: CFG.exportEstado === 200,
      status: CFG.exportEstado,
      headers: { get: () => CFG.exportNombre &&
        `attachment; filename="${CFG.exportNombre}"` },
      json: async () => ({ detail: 'Todavía no hay nada que exportar.' }),
      blob: async () => ({}),
    };
  }
  return { ok: CFG.estado === 200, status: CFG.estado, json: async () => CFG.runs };
};
global.console = { warn(...a) { resultado.warns = (resultado.warns || 0) + 1; }, log() {} };
"""

_EPILOGO = """
(async () => {
  await new Promise((r) => setTimeout(r, 0));
  resultado.sessionGuardado = localStorage._d.get('rcm-demo-session') ?? null;
  resultado.sendDeshabilitado = elementos.send.disabled;
  if (CFG.pulsaExportar && elementos.exportar._h?.click) {
    await elementos.exportar._h.click();
    await new Promise((r) => setTimeout(r, 0));
    resultado.descargado = resultado.descarga;
  }
  if (CFG.pulsaNuevo && elementos.nuevo._h?.click) {
    elementos.nuevo._h.click();
    resultado.sessionTrasNuevo = localStorage._d.get('rcm-demo-session') ?? null;
    resultado.previaTrasNuevo = localStorage._d.get('rcm-demo-session-previa') ?? null;
  }
  process.stdout.write(JSON.stringify(resultado));
  // El revokeObjectURL de la descarga deja un timer de 10 s vivo; sin salir
  // explícitamente cada caso tardaría eso en terminar.
  process.exit(0);
})();
"""


def correr(**cfg) -> dict:
    cfg = {
        "busqueda": "?key=abc", "store": [], "estado": 404, "runs": [],
        "pulsaNuevo": False, "confirma": True, "bloquea": False,
        "pulsaExportar": False, "exportEstado": 200,
        "exportNombre": "AMEF_P-101.xlsx",
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
        # El usuario sigue en texto plano; el bot va como árbol renderizado.
        assert "user|Hola, la bomba P200" in reanudada["burbujas"]
        assert any(
            b.startswith("bot|") and "Perfecto, registremos." in b
            for b in reanudada["burbujas"]
        ), reanudada["burbujas"]

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


class TestBotonExportar:
    """El cliente debe poder llevarse su Excel sin pedírselo al facilitador."""

    def test_pide_el_entregable_de_su_sesion_con_la_llave_en_cabecera(self):
        # La llave nunca debe ir en la URL de descarga: acabaría en el historial
        # del navegador del cliente.
        r = correr(store={"rcm-demo-session": "demo-mia"}, pulsaExportar=True)
        assert "/exports/demo-mia" in r["fetches"]
        assert r["cabeceras"] == {"Authorization": "Bearer abc"}
        assert not any("key=" in f for f in r["fetches"])

    def test_descarga_con_el_nombre_que_decide_el_servidor(self):
        # El navegador no conoce el TAG del equipo; el nombre viene en la
        # cabecera Content-Disposition.
        r = correr(pulsaExportar=True, exportNombre="AMEF_P-200.xlsx")
        assert r["descargado"] == "AMEF_P-200.xlsx"

    def test_avisa_cuando_el_entregable_es_solo_un_borrador(self):
        r = correr(pulsaExportar=True, exportNombre="BORRADOR_AMEF_P-200.xlsx")
        assert any("borrador" in a.lower() for a in r["avisos"]), r["avisos"]

    def test_explica_cuando_todavia_no_hay_nada_que_exportar(self):
        r = correr(pulsaExportar=True, exportEstado=404)
        assert any("nada que exportar" in a for a in r["avisos"]), r["avisos"]
        assert not r.get("descargado")

    def test_sin_llave_no_intenta_descargar(self):
        r = correr(busqueda="?session=demo-mia", pulsaExportar=True)
        assert not any("/exports/" in f for f in r["fetches"])


def render(texto: str) -> str:
    """Serialización del árbol que produce el renderizador para una respuesta."""
    r = correr(
        busqueda="?key=abc&session=demo-previa",
        estado=200,
        runs=[{"status": "COMPLETED", "run_input": "x", "content": texto}],
    )
    burbujas = [b for b in r["burbujas"] if b.startswith("bot|")]
    assert burbujas, r["burbujas"]
    assert not r.get("warns"), "el renderizador cayó al fallback"
    return burbujas[0][4:]


class TestMarkdown:
    """El cliente lee `**Equipo:**` en pantalla. Medido en producción: 104
    asteriscos visibles, 0 <strong>, 0 listas."""

    def test_negrita(self):
        assert "strong()[Equipo]" in render("El **Equipo** está listo")

    def test_cursiva_con_asterisco_y_guion_bajo(self):
        assert "em()[así]" in render("Se lee *así*")
        assert "em()[asá]" in render("Se lee _asá_")

    def test_codigo_en_linea(self):
        assert "code(P-101)" in render("El tag es `P-101`")

    def test_titulo(self):
        salida = render("## Resumen del análisis")
        assert "div()" in salida and "className=md-h" in salida
        assert "Resumen del análisis" in salida

    def test_lista_numerada(self):
        salida = render("1. Primero\n2. Segundo\n3. Tercero")
        assert salida.startswith("ol()[")
        assert salida.count("li()") == 3

    def test_lista_con_vinetas(self):
        salida = render("- Uno\n- Dos")
        assert salida.startswith("ul()[")
        assert salida.count("li()") == 2

    def test_parrafos_separados_por_linea_en_blanco(self):
        salida = render("Primero.\n\nSegundo.")
        assert salida.count("p()") == 2

    def test_bloque_cercado(self):
        salida = render("Ejemplo:\n```\nRPN = S x O x D\n```")
        assert "pre()" in salida and "code(RPN = S x O x D)" in salida

    def test_negrita_dentro_de_lista(self):
        # El caso real del Facilitador: listas con términos en negrita.
        salida = render("1. Definir los **límites físicos**\n2. Describir las **interfaces**")
        assert salida.count("strong()") == 2

    def test_linea_horizontal(self):
        # El Facilitador separa secciones con `---`; sin esto sale literal.
        assert "hr()" in render("Arriba\n\n---\n\nAbajo")
        assert "hr()" in render("***")

    def test_guion_suelto_sigue_siendo_vineta(self):
        salida = render("- un punto")
        assert "ul()" in salida and "hr()" not in salida

    def test_emoji_y_negrita_conviven(self):
        assert "strong()[Equipo:]" in render("🎯 **Equipo:** Bomba centrífuga")


class TestSeguridadMarkdown:
    """El texto viene del modelo, que repite lo que escribe el usuario."""

    def test_html_crudo_se_queda_como_texto(self):
        salida = render('Mira <img src=x onerror=alert(1)> esto')
        assert "img" not in salida.replace("<img src=x onerror=alert(1)>", "")
        assert "<img src=x onerror=alert(1)>" in salida

    def test_script_no_se_convierte_en_elemento(self):
        salida = render("<script>alert(1)</script>")
        assert "<script>alert(1)</script>" in salida
        assert "script()" not in salida

    def test_enlace_javascript_no_genera_ancla(self):
        salida = render("[pulsa](javascript:alert(1))")
        assert "href=" not in salida, "generó un ancla con esquema javascript:"
        assert "javascript:alert(1)" in salida  # queda como texto visible

    def test_enlace_data_no_genera_ancla(self):
        salida = render("[x](data:text/html,<script>alert(1)</script>)")
        assert "a(" not in salida

    def test_enlace_https_abre_en_pestana_nueva(self):
        salida = render("Ver [la norma](https://ejemplo.com/ja1011)")
        assert "href=https://ejemplo.com/ja1011" in salida
        assert "target=_blank" in salida and "rel=noopener noreferrer" in salida

    def test_exports_con_salto_de_directorio_no_es_clicable(self):
        # `/exports/../..` resuelve fuera de /exports: un enlace anunciado como
        # descarga no debe poder apuntar a otro sitio.
        assert "href=" not in render("[x](/exports/../../otra)")
        assert "href=" not in render("[x](/exports/..%2Fotra)".replace("%2F", "\\"))

    def test_negrita_y_cursiva_juntas_no_dejan_asteriscos(self):
        salida = render("Esto es ***muy importante***")
        assert "strong()" in salida and "em()" in salida
        assert "*" not in salida

    def test_enlace_relativo_de_exports_es_clicable(self):
        # Lo que emite export_excel: el cliente baja su Excel de un clic.
        salida = render("Descarga: [AMEF](/exports/s1/AMEF_P200.xlsx?key=k)")
        assert "href=/exports/s1/AMEF_P200.xlsx?key=k" in salida
        assert "target=_blank" not in salida  # misma pestaña: es una descarga


class TestTextoDelRun:
    """agno concatena los mensajes del asistente sin separador cuando el turno
    lleva llamada a herramienta: «…un resumen rápido:**Resumen:**»."""

    def _run(self, mensajes, content):
        return {"status": "COMPLETED", "run_input": "x",
                "messages": mensajes, "content": content}

    def test_separa_los_mensajes_del_turno(self):
        r = correr(
            busqueda="?key=abc&session=demo-previa", estado=200,
            runs=[self._run(
                [{"role": "system", "content": "s"},
                 {"role": "user", "content": "resume"},
                 {"role": "assistant", "content": "Un resumen rápido:"},
                 {"role": "tool", "content": "t"},
                 {"role": "assistant", "content": "**Resumen:** todo bien"}],
                "Un resumen rápido:**Resumen:** todo bien")],
        )
        salida = [b for b in r["burbujas"] if b.startswith("bot|")][0]
        assert salida.count("p()") == 2, salida
        assert "rápido:strong" not in salida

    def test_ignora_los_mensajes_de_turnos_anteriores(self):
        r = correr(
            busqueda="?key=abc&session=demo-previa", estado=200,
            runs=[self._run(
                [{"role": "assistant", "content": "de un turno viejo"},
                 {"role": "user", "content": "nueva pregunta"},
                 {"role": "assistant", "content": "respuesta de ahora"}],
                "respuesta de ahora")],
        )
        salida = [b for b in r["burbujas"] if b.startswith("bot|")][0]
        assert "de un turno viejo" not in salida
        assert "respuesta de ahora" in salida

    def test_cae_a_content_si_no_hay_mensajes(self):
        r = correr(
            busqueda="?key=abc&session=demo-previa", estado=200,
            runs=[{"status": "COMPLETED", "run_input": "x", "content": "solo content"}],
        )
        assert any("solo content" in b for b in r["burbujas"])
