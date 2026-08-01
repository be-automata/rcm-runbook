"""El script de verificación en producción no tenía ni un test.

Es la tercera ronda seguida en que se arregla sin nada que lo sostenga: se pudo
reducir `ESPERADOS` a un solo criterio, o devolver el denominador dinámico, con
la suite entera en verde. Y es el único que cierra los once criterios que
necesitan un turno real del modelo, así que un fallo suyo no lo ve nadie.

Aquí se prueban sus piezas puras. Lo que habla con producción no se simula: eso
se ejecuta de verdad, y su salida se lee.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

_RUTA = Path(__file__).resolve().parents[2] / "scripts" / "verificar_en_produccion.py"


def _modulo():
    spec = importlib.util.spec_from_file_location("verificar_en_produccion", _RUTA)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


V = _modulo()


class TestElEquipoSeLeeDelEstadoNoDelHistorial:
    """La aserción original era `"Ana" in json.dumps(sesión)`, y ese JSON incluye
    el historial de mensajes: «Analicemos», con la que el propio script abre la
    sesión, contiene «Ana». Daba True con el equipo vacío."""

    def test_una_sesion_vacia_no_cuela_por_el_historial(self):
        sesion = {
            "session_data": {
                "session_state": {"rcm": {"team": []}},
                "runs": [{"input": "Analicemos la bomba P-104"}],
            }
        }
        assert V._equipo_registrado(sesion) == []

    def test_lee_los_nombres_del_estado(self):
        sesion = {"session_state": {"rcm": {"team": [
            {"name": "Ana Pérez", "role": "mantenimiento"},
            {"name": "Luis Gómez", "role": "operaciones"},
        ]}}}
        assert V._equipo_registrado(sesion) == ["Ana Pérez", "Luis Gómez"]


class TestLasFasesInventadasSeDetectanTambienEnPlural:
    """«las fases 2 y 3 siguen pendientes» es la forma natural en español para
    enumerar varias, y es exactamente la del síntoma: el detector solo veía el
    singular, así que el criterio se aprobaba con una lista íntegramente
    inventada."""

    @pytest.mark.parametrize(
        ("texto", "esperado"),
        [
            ("la Fase 2 sigue pendiente", {"2"}),
            ("las fases 2 y 3 siguen pendientes", {"2", "3"}),
            ("fases 2, 3 y 4 pendientes", {"2", "3", "4"}),
            ("Fase 3 — AMEF sin modos", {"3"}),
            ("no menciona ninguna", set()),
        ],
    )
    def test_cuenta_las_fases(self, texto, esperado):
        assert V._fases_mencionadas(texto) == esperado


class TestLosFaltantesSalenDeLaHerramienta:
    """El endpoint del botón devuelve un BORRADOR válido, no una lista de
    bloqueadores: preguntarle por los faltantes daba siempre la lista vacía."""

    def test_lee_el_resultado_de_export_excel(self):
        salida = {"tools": [
            {"tool_name": "get_progress", "result": "- esto no cuenta"},
            {"tool_name": "export_excel", "result": (
                "❌ El análisis está incompleto:\n"
                "- [Fase 1] Falta el TAG o código técnico del activo.\n"
                "- [Fase 1] Faltan los límites físicos del análisis."
            )},
        ]}
        faltantes = V._faltantes_de_la_herramienta(salida)
        assert len(faltantes) == 2
        assert all(f.startswith("[Fase 1]") for f in faltantes)

    def test_sin_llamada_a_export_excel_no_inventa_faltantes(self):
        assert V._faltantes_de_la_herramienta({"tools": [{"tool_name": "get_progress"}]}) == []


class TestElDenominadorNoEncoge:
    """Con el total dinámico, un criterio que dejaba de ser evaluable bajaba el
    denominador y el script imprimía «8/8 en verde» con salida 0: una regresión
    se manifestaba como menos criterios comprobados. Luego, al fijarlo, meter el
    27 —que depende de ALTA-2— producía «8/9» en un sistema sano."""

    def test_los_condicionales_estan_declarados_y_no_se_solapan(self):
        assert set(V.CONDICIONALES) == {8, 27}
        assert not set(V.CONDICIONALES) & set(V.ESPERADOS)

    def test_estan_los_criterios_que_el_guion_promete(self):
        # Los once del guion menos los condicionales, el no ejecutado y el que
        # se pasó a revisión humana.
        del_guion = {1, 4, 8, 10, 23, 25, 26, 27, 29, 36, 40}
        assert set(V.ESPERADOS) == del_guion - {8, 26, 27, 40}

    def test_lo_que_pasa_a_revision_humana_esta_declarado(self):
        # Y no se solapa con lo que sí se puntúa: un criterio no puede estar en
        # las dos listas, o saldría contado dos veces con dos varas distintas.
        assert set(V.REQUIEREN_OJO) == {40}
        assert not set(V.REQUIEREN_OJO) & set(V.ESPERADOS)
        assert not set(V.REQUIEREN_OJO) & set(V.CONDICIONALES)


class TestElSondeoSeParaSiElProveedorNoAtiende:
    """Correr los criterios contra un sistema caído solo produce ruido. Y un 502
    del borde llega como HTML: reventar con JSONDecodeError contradice justo lo
    que la función promete."""

    class _Respuesta:
        def __init__(self, status, cuerpo=None, json_valido=True):
            self.status_code = status
            self._cuerpo = cuerpo or {}
            self._valido = json_valido

        def json(self):
            if not self._valido:
                raise ValueError("no es JSON")
            return self._cuerpo

    class _Cliente:
        def __init__(self, respuesta):
            self._r = respuesta

        def get(self, *a, **k):
            return self._r

    def test_un_503_para_la_corrida(self):
        r = self._Respuesta(503, {"detalle": "La cuenta del proveedor no tiene saldo."})
        atiende, detalle = V._proveedor_atiende(self._Cliente(r))
        assert atiende is False
        assert "saldo" in detalle

    def test_un_html_del_borde_no_revienta(self):
        r = self._Respuesta(502, json_valido=False)
        atiende, detalle = V._proveedor_atiende(self._Cliente(r))
        assert atiende is False
        assert "502" in detalle

    def test_un_200_deja_seguir(self):
        r = self._Respuesta(200, {"detalle": "El proveedor del modelo responde."})
        atiende, _ = V._proveedor_atiende(self._Cliente(r))
        assert atiende is True


class TestNoDefinirNoEsInventar:
    """El detector miraba 90 caracteres desde la primera aparición del código y
    marcaba como inventado uno correctamente listado más abajo. Dio un falso
    positivo contra una respuesta que era correcta: «FTS — Falla en arrancar
    cuando es requerido». El criterio dice «no inventa el significado», y no
    definirlo no es inventárselo."""

    @property
    def REALES(self) -> dict[str, str]:  # noqa: N802
        # El catálogo real del cliente, que es lo que devuelve la herramienta.
        from rcm_runbook.models.catalogs import fixture

        return {c.code: c.definition for c in fixture().menu.iso14224_failure_mode_codes}

    def test_una_respuesta_correcta_no_se_marca(self):
        texto = (
            "- **FTS** — Falla en arrancar cuando es requerido\n"
            "- **STP** — Falla para detenerse cuando es requerido"
        )
        definidos, inventados = V._codigos_definidos(texto, self.REALES)
        assert definidos == ["FTS", "STP"]
        assert inventados == []

    def test_listar_sin_definir_no_es_inventar(self):
        texto = "Los códigos disponibles son FTS, STP, BRD, HIO y LOO."
        definidos, inventados = V._codigos_definidos(texto, self.REALES)
        assert definidos == [] and inventados == []

    def test_un_significado_falso_si_se_caza(self):
        texto = "- **FTS** — Fuga total del sistema\n- **STP** — Obstrucción"
        _, inventados = V._codigos_definidos(texto, self.REALES)
        assert inventados, "no cazó el invento"
        assert inventados[0].startswith("FTS")
        assert "Fuga total" in inventados[0], "no dice QUÉ inventó"
        assert "encaja con" in inventados[0], "no dice con qué código encaja"

    def test_lo_que_no_encaja_con_nada_del_catalogo_no_se_acusa(self):
        # Límite conocido y deliberado: «HIO — Exceso de calor» es un invento,
        # pero no comparte palabras con NINGUNA definición del catálogo, así que
        # no hay nada contra lo que contrastarlo. Acusarlo exigiría un umbral de
        # parecido, y los tres intentos anteriores fallaron justo por elegir uno
        # a mano. Lo que sí se caza es la inversión —atribuirle a un código la
        # definición de otro—, que es lo que hace daño.
        texto = "- **FTS** — Falla en arrancar\n- **HIO** — Exceso de calor"
        definidos, inventados = V._codigos_definidos(texto, self.REALES)
        assert definidos == ["FTS", "HIO"]
        assert inventados == []

    def test_la_inversion_si_se_caza(self):
        texto = "- **HIO** — Baja salida\n- **LOO** — Alta Salida"
        _, inventados = V._codigos_definidos(texto, self.REALES)
        assert inventados, "confundir alta con baja salida pasó desapercibido"


class TestElVeredictoDelScript:
    """`main()` no tenía cobertura, y ahí viven los dos arreglos del veredicto:
    el denominador fijo y «un obligatorio sin evaluar cuenta como fallo». Se
    podían revertir los dos con la suite entera en verde."""

    def _hallazgo(self, criterio: int, ok: bool = True) -> dict:
        return {"criterio": criterio, "descripcion": f"criterio {criterio}",
                "ok": ok, "evidencia": ""}

    def _todos_verdes(self) -> list[dict]:
        return [self._hallazgo(n) for n in V.ESPERADOS]

    def test_todo_verde_sale_cero(self):
        assert V._veredicto(self._todos_verdes(), [], []) == 0

    def test_un_obligatorio_en_rojo_sale_uno(self):
        hallazgos = self._todos_verdes()
        hallazgos[0]["ok"] = False
        assert V._veredicto(hallazgos, [], []) == 1

    def test_un_obligatorio_sin_evaluar_cuenta_como_fallo(self):
        # Antes solo se imprimía un aviso: una regresión se manifestaba como
        # menos criterios comprobados en vez de como error.
        hallazgos = self._todos_verdes()[:-1]
        assert V._veredicto(hallazgos, [], []) == 1

    def test_el_denominador_no_encoge(self, capsys):
        hallazgos = self._todos_verdes()[:-1]
        V._veredicto(hallazgos, [], [])
        salida = capsys.readouterr().out
        assert f"/{len(V.ESPERADOS)} criterios obligatorios" in salida, (
            "el total bajó con los criterios evaluados"
        )

    def test_un_condicional_en_rojo_tambien_falla(self):
        # Miden, pero si se llegan a juzgar y salen mal, es un fallo.
        hallazgos = [*self._todos_verdes(), self._hallazgo(27, ok=False)]
        assert V._veredicto(hallazgos, [], []) == 1

    def test_no_dice_no_evaluable_de_algo_que_midio(self, capsys):
        V._veredicto(self._todos_verdes(), ["[8] la compuerta: 2/3"], [])
        salida = capsys.readouterr().out
        assert "[8] no evaluable" not in salida
        assert "[8] la compuerta: 2/3" in salida

    def test_nombra_los_obligatorios_que_faltan(self, capsys):
        V._veredicto(self._todos_verdes()[:-1], [], [])
        salida = capsys.readouterr().out
        assert "SIN EVALUAR" in salida
        assert f"[{V.ESPERADOS[-1]}]" in salida


class TestSeDetectaElInventoEnElCodigoPreguntado:
    """El caso central del criterio 29 no lo cubría nada: «QQQ1 no existe, pero
    por su forma sería 'Falla de calidad tipo 1'» daba «lo declara ausente:
    True, inventados: ninguno» y aprobaba."""

    def test_decir_solo_que_no_existe_es_correcto(self):
        assert not V._significado_atribuido(
            "El código **'QQQ1' no existe en el catálogo ISO 14224**.", "QQQ1")

    def test_atribuirle_un_significado_se_caza(self):
        for frase in (
            "QQQ1 no existe, pero por su forma sería 'Falla de calidad tipo 1'.",
            "QQQ1 podría significar una falla de calidad.",
            "| **QQQ1** | Falla de calidad tipo 1 |",
        ):
            assert V._significado_atribuido(frase, "QQQ1"), f"se coló: {frase}"

    def test_listar_los_codigos_reales_no_cuenta(self):
        assert not V._significado_atribuido(
            "QQQ1 no existe. Los disponibles son FTS, STP y HIO.", "QQQ1")


class TestElDetectorLeeLosFormatosQueElAgenteUsa:
    """El regex excluía `|`, y el agente responde con una tabla markdown: contra
    la respuesta real de producción no consideraba definido ni un código, así que
    la mitad de «no inventa» quedaba vacua. Cambiar una medición porque falla es
    la forma de aflojar la vara sin darse cuenta."""

    @property
    def REALES(self) -> dict[str, str]:  # noqa: N802
        # El catálogo real del cliente, que es lo que devuelve la herramienta.
        from rcm_runbook.models.catalogs import fixture

        return {c.code: c.definition for c in fixture().menu.iso14224_failure_mode_codes}

    def test_tabla_markdown_correcta(self):
        texto = ("| **FTS** | Falla en arrancar cuando es requerido |\n"
                 "| **STP** | Falla para detenerse |")
        definidos, inventados = V._codigos_definidos(texto, self.REALES)
        assert definidos == ["FTS", "STP"] and inventados == []

    def test_tabla_markdown_con_invento(self):
        texto = "| **FTS** | Fuga total del sistema |\n| **STP** | Obstrucción |"
        _, inventados = V._codigos_definidos(texto, self.REALES)
        assert inventados, "el formato que usa de verdad se colaba"
        assert inventados[0].startswith("FTS")

    def test_parentesis_y_verbos(self):
        for texto in ("El código FTS (Fuga Total del Sistema) es común.",
                      "FTS significa Fuga total del sistema."):
            _, inventados = V._codigos_definidos(texto, self.REALES)
            assert inventados, f"se coló: {texto}"


class TestElCriterio29Entero:
    """El veredicto del 29 sale de comparar CONJUNTOS, no de trocear prosa.

    Cuatro rondas seguidas produjeron cuatro cortes distintos del texto y cuatro
    veredictos distintos sobre las mismas respuestas, sin que el producto
    cambiara: la última ponía en rojo 129 de 380 respuestas correctas según qué
    conector eligiera el modelo. Lo que se decide aquí es lo que no necesita
    gramática: que declare ausente el código y que no use siglas que el catálogo
    del cliente no tiene. Lo demás se recoge y lo mira una persona.
    """

    @property
    def REALES(self) -> dict[str, str]:  # noqa: N802
        from rcm_runbook.models.catalogs import fixture

        return {c.code: c.definition for c in fixture().menu.iso14224_failure_mode_codes}

    def _juzgar(self, texto: str):
        return V._juzgar_codigo_iso(texto, "QQQ1", self.REALES)

    def test_respuesta_correcta_aprueba(self):
        ok, _, _ = self._juzgar(
            "El código **'QQQ1' no existe en el catálogo ISO 14224**.\n"
            "| **FTS** | Falla en arrancar cuando es requerido |"
        )
        assert ok

    def test_inventar_el_significado_del_preguntado_falla(self):
        # Esto SÍ se decide sin gramática: el catálogo no tiene el código, así
        # que cualquier significado que se le dé es inventado.
        ok, evidencia, _ = self._juzgar(
            "QQQ1 no existe, pero por su forma sería 'Falla de calidad tipo 1'."
        )
        assert not ok
        assert "Falla de calidad" in evidencia

    def test_una_sigla_fuera_del_catalogo_se_anota_pero_no_suspende(self):
        """Decidirlo exigía una lista blanca de siglas del oficio, y esa lista
        no converge: con ella puesta, 72 de 79 siglas del dominio —`RPM`,
        `BAR`, `ASME`, `OREDA`, `SSO`, el TAG `TK-12`, la cabecera `| MODO |`—
        producían acusación falsa, y 11 de cada 12 respuestas correctas salían
        en rojo. El vocabulario técnico no está acotado. Se anota y se revisa.
        """
        ok, _, revisar = self._juzgar(
            "QQQ1 no existe en el catálogo. Los modos son FTS, STP y XYZ."
        )
        assert ok, "una sigla desconocida no puede suspender por sí sola"
        assert any("XYZ" in linea for linea in revisar), "y tampoco puede callarse"

    @pytest.mark.parametrize(
        "texto",
        [
            "QQQ1 no existe. Para la bomba PT-100 revise el modo FTS.",
            "QQQ1 no figura en ISO 14224. Puede consultarlo en su CMMS (SAP).",
            "QQQ1 no existe. La velocidad nominal es 3600 RPM y la presión 12 BAR.",
            "QQQ1 no existe. Normas de referencia: ASME PCC-3 y ANSI/API 610.",
            "QQQ1 no aparece. En términos de SSO/EHS el equipo TK-12 sigue operable.",
            "QQQ1 no existe. Le devuelvo el resultado en JSON si lo prefiere.",
            "QQQ1 no existe. El KPI a mirar es MTBF y el plan PM sigue igual.",
            "QQQ1 no existe.\n| MODO | DESCRIPCION |\n| FTS | Falla en arrancar |",
            "QQQ1 no existe. El prefijo QQQ tampoco corresponde a ninguna familia.",
            "**NO** existe el código QQQ1 en el catálogo del cliente.",
        ],
    )
    def test_el_vocabulario_del_oficio_no_suspende_una_respuesta_correcta(self, texto):
        assert self._juzgar(texto)[0], f"salió en rojo por su vocabulario: {texto[:60]}"

    def test_no_decir_que_falta_falla(self):
        ok, _, _ = self._juzgar("| **FTS** | Falla en arrancar cuando es requerido |")
        assert not ok, "no dijo que el código preguntado no está en el catálogo"

    @pytest.mark.parametrize(
        "forma",
        [
            "- {c} — {d}", "**{c}** — {d}", "| {c} | {d} |", "{c} – {d}",
            "{c}: {d}", "{c} = {d}", "El código {c} — {d}", "Además {c} — {d}",
            "También {c}: {d}", "{c} → {d}", "_{c}_ — {d}", "`{c}` — {d}",
            "1. {c} – {d}", "{c} significa {d}",
        ],
    )
    def test_el_veredicto_no_depende_del_formato_ni_del_conector(self, forma):
        """El defecto que mató a las cuatro versiones anteriores del detector.

        Cada una cubría unas formas y se quedaba ciega en otras, y el flanco no
        se estrechaba: la de la ronda 22 aprobaba «y FOV — …» y suspendía
        «También FOV — …» sobre el mismo contenido. Aquí las catorce formas
        tienen que dar el mismo veredicto, porque el veredicto no las mira.
        """
        reales = self.REALES
        cuerpo = "\n".join(
            forma.format(c=c, d=d) for c, d in list(reales.items())[:6]
        )
        ok, _, _ = self._juzgar(f"QQQ1 no está en el catálogo.\n{cuerpo}")
        assert ok, f"el eco correcto del catálogo salió en rojo con «{forma}»"

    def test_una_sigla_inventada_con_digito_tambien_se_anota(self):
        # El propio código que se pregunta —QQQ1— lleva dígito, así que un
        # invento con esa misma forma es el más probable, y sin el dígito en el
        # patrón sería invisible.
        _, _, revisar = self._juzgar(
            "QQQ1 no existe en el catálogo, pero XYZ1 sí es un modo válido."
        )
        assert any("XYZ1" in linea for linea in revisar)

    def test_un_catalogo_vacio_es_un_fallo_no_un_silencio(self):
        """Descarte silencioso nº 18, y de los caros: en verde.

        Con el catálogo vacío no había nada contra qué comparar, así que una
        respuesta que se inventaba tres códigos aprobaba, y la evidencia decía
        «códigos fuera del catálogo: ninguno» —que se lee como una medición
        hecha—. El criterio pide usar `explain_iso_code`: si de su salida no
        sale ni un código, o no se llamó o el instrumento dejó de saber leerla,
        y las dos cosas hay que verlas.
        """
        ok, evidencia, _ = V._juzgar_codigo_iso(
            "QQQ1 no existe en el catálogo. Los válidos son ZZZ9, WWW2 y KKK5.",
            "QQQ1",
            {},
        )
        assert not ok, "aprobó sin catálogo contra el que comparar"
        assert "CATÁLOGO VACÍO" in evidencia

    @pytest.mark.parametrize(
        ("frase", "esperado"),
        [
            ("QQQ1 significa Quality Quick Quench.", "Quality Quick Quench."),
            ("QQQ1 quiere decir falla del sistema de calidad.",
             "falla del sistema de calidad."),
            ("QQQ1 no existe, pero por su forma sería «Falla de calidad».",
             "Falla de calidad"),
        ],
    )
    def test_los_verbos_de_atribucion_estan_cubiertos(self, frase, esperado):
        # «significa» y «quiere decir» se añadieron sin un solo test que los
        # mirara: quitarlos dejaba la suite entera en verde.
        assert V._significado_atribuido(frase, "QQQ1") == esperado

    @pytest.mark.parametrize(
        "negacion",
        [
            "QQQ1 no quiere decir nada en ISO 14224.",
            "QQQ1 significa que la consulta no devolvió resultados.",
            "QQQ1 — no se encuentra en la base de códigos.",
            "QQQ1 — código no reconocido por la herramienta.",
            "QQQ1: sin correspondencia en la norma.",
            "QQQ1 - no consta en el catálogo cargado.",
        ],
    )
    def test_negar_con_esos_mismos_verbos_no_es_atribuir(self, negacion):
        # El riesgo simétrico de cubrir los verbos: «no quiere decir nada» se
        # leía como que le atribuía el significado «nada en ISO 14224».
        assert not V._significado_atribuido(negacion, "QQQ1"), (
            f"leyó una negación como atribución: {negacion}"
        )

    def test_una_sigla_de_dos_letras_no_es_un_codigo_del_catalogo(self):
        # El ancho del patrón es un dial: con `{2,4}`, `PT` de un TAG, `PM` de
        # un plan y `NO` en mayúsculas se anotaban como códigos ajenos. Los
        # códigos del cliente son de tres letras.
        reales = self.REALES
        _, _, revisar = V._juzgar_codigo_iso(
            "QQQ1 no existe. Para la bomba PT-100, el plan PM sigue igual.",
            "QQQ1", reales,
        )
        anotadas = " ".join(x for x in revisar if "siglas que el catálogo" in x)
        assert "PT" not in anotadas and "PM" not in anotadas, anotadas

    def test_las_siglas_del_dominio_no_se_confunden_con_codigos(self):
        # «RCM», «ISO», «AMEF» y compañía aparecen en cualquier respuesta y no
        # son modos de falla. La lista es corta y cerrada, y una sigla nueva da
        # una acusación VISIBLE —no un descarte mudo— que se arregla añadiéndola.
        ok, evidencia, _ = self._juzgar(
            "QQQ1 no existe en el catálogo ISO 14224. En el análisis RCM usamos "
            "el AMEF y lo exportamos a XLSX para el CMMS."
        )
        assert ok, f"confundió una sigla del dominio con un código: {evidencia}"


class TestLaMedicionDeLaCompuerta:
    """El conteo vivía dentro de main y desconectarlo no rompía nada: el
    criterio 8 podía reportar siempre 0/3 sin que nadie se enterara."""

    def test_dice_la_proporcion_real(self):
        assert "2/3" in V._medicion_compuerta(2, 3)
        assert "0/3" in V._medicion_compuerta(0, 3)

    def test_dice_que_mide_y_por_que(self):
        linea = V._medicion_compuerta(2, 3)
        assert "ALTA-2" in linea
        assert "botón" in linea, "no dice cuál es el camino garantizado"


class TestElResumenCuentaSoloLosObligatorios:
    """`verdes` contando todos los hallazgos inflaba el numerador con los
    condicionales: «9/8 criterios obligatorios en verde»."""

    def test_un_condicional_verde_no_infla_el_numerador(self, capsys):
        hallazgos = [
            {"criterio": n, "descripcion": "", "ok": True, "evidencia": ""}
            for n in V.ESPERADOS
        ]
        hallazgos.append({"criterio": 27, "descripcion": "", "ok": True, "evidencia": ""})
        V._veredicto(hallazgos, [], [])
        salida = capsys.readouterr().out
        assert f"{len(V.ESPERADOS)}/{len(V.ESPERADOS)} criterios obligatorios" in salida

    def test_los_condicionales_se_describen(self):
        # Con el texto vacío, el aviso «no evaluable» no dice de qué.
        for n, desc in V.CONDICIONALES.items():
            assert len(desc) > 20, f"[{n}] sin descripción utilizable: {desc!r}"


class TestElConteoDeLlamadas:
    """El bucle vivía en main() y no había forma de probarlo: el criterio 8
    podía reportar siempre 0/3 sin que nada lo notara."""

    def _run(self, *herramientas):
        return {"tools": [{"tool_name": h} for h in herramientas]}

    def test_cuenta_los_turnos_donde_se_llamo(self):
        salidas = [
            self._run("export_excel"),
            self._run("get_progress"),
            self._run("get_progress", "export_excel"),
        ]
        assert V._veces_que_llamo(salidas, "export_excel") == 2

    def test_cero_cuando_nunca_se_llamo(self):
        assert V._veces_que_llamo([self._run("get_progress")], "export_excel") == 0

    def test_un_turno_sin_herramientas_no_cuenta(self):
        assert V._veces_que_llamo([{"tools": []}, {}], "export_excel") == 0


class TestUnaCaidaDelProveedorNoSeCulpaAlProducto:
    """La cuenta se quedó sin saldo A MITAD de corrida: el script siguió
    puntuando y marcó en rojo seis criterios que estaban bien —«2/8 obligatorios
    en verde» con el producto intacto—. Un instrumento que acusa al producto de
    su propia avería es peor que no medir."""

    @pytest.mark.parametrize(
        "mensaje",
        [
            # Una marca por caso: el primer intento metía dos en el mismo texto,
            # así que quitar una del detector no rompía nada.
            "Error code: 400 - your credit balance is too low",
            "Error code: 400 - {'type': 'invalid_request_error'}",
            "Error code: 429 - rate_limit_error",
            "Error code: 529 - overloaded_error",
            "Error code: 401 - authentication_error",
        ],
    )
    def test_reconoce_los_fallos_del_proveedor(self, mensaje):
        assert V._es_fallo_del_proveedor({"content": mensaje}), mensaje[:40]

    def test_el_turno_aborta_en_vez_de_devolver_el_error(self):
        # El cableado, no solo el detector: sin esto el turno devolvía el error
        # como si fuera una respuesta y el criterio se marcaba en rojo.
        class _R:
            status_code = 200

            @staticmethod
            def raise_for_status():
                pass

            @staticmethod
            def json():
                return {"content": "Error code: 400 - your credit balance is too low"}

        class _Cliente:
            @staticmethod
            def post(*a, **k):
                return _R()

        with pytest.raises(V.ProveedorCaido):
            V._turno(_Cliente(), "uat-x", "hola")

    def test_un_turno_normal_pasa(self):
        class _R:
            status_code = 200

            @staticmethod
            def raise_for_status():
                pass

            @staticmethod
            def json():
                return {"content": "Perfecto, registro esa función."}

        class _Cliente:
            @staticmethod
            def post(*a, **k):
                return _R()

        assert V._turno(_Cliente(), "uat-x", "hola")["content"].startswith("Perfecto")

    def test_una_respuesta_normal_no_lo_es(self):
        assert not V._es_fallo_del_proveedor(
            {"content": "Perfecto, registro esa función primaria del activo."}
        )

    def test_un_turno_vacio_no_lo_es(self):
        assert not V._es_fallo_del_proveedor({})

    def test_la_excepcion_existe_y_es_propia(self):
        # Distinguirla importa: una corrida truncada no es un criterio en rojo.
        assert issubclass(V.ProveedorCaido, RuntimeError)


class TestCumplirElCriterioNoPuedeHacerloFallar:
    """Apreté el detector hasta romper respuestas correctas: negar que el código
    exista —que es cumplir la primera mitad del criterio— se marcaba como
    significado inventado, y expandir la sigla en inglés también. Es el error de
    la ronda 13 con el signo invertido: aquella aflojó la vara, esta la apretó."""

    @property
    def REALES(self) -> dict[str, str]:  # noqa: N802
        # El catálogo real del cliente, que es lo que devuelve la herramienta.
        from rcm_runbook.models.catalogs import fixture

        return {c.code: c.definition for c in fixture().menu.iso14224_failure_mode_codes}

    def _ok(self, texto: str) -> bool:
        return V._juzgar_codigo_iso(texto, "QQQ1", self.REALES)[0]

    @pytest.mark.parametrize(
        "texto",
        [
            "'QQQ1' no existe.\n| **FTS** | Falla en arrancar cuando es requerido |",
            "QQQ1 no existe en el catálogo.\n- **FTS** — Falla en arrancar",
            "**QQQ1** — no está en el catálogo ISO 14224 de este cliente.",
            "| QQQ1 | No existe en el catálogo ISO 14224 |",
            "QQQ1 no existe.\nFTS (Fail To Start) — Falla en arrancar cuando es requerido",
            "El código QQQ1 no significa nada aquí: no figura en ISO 14224.",
            "QQQ1 no existe. FTS es el código más frecuente en bombas centrífugas.",
        ],
    )
    def test_una_respuesta_correcta_aprueba(self, texto):
        assert self._ok(texto), f"falso positivo: {texto[:60]}"

    @pytest.mark.parametrize(
        "texto",
        [
            "QQQ1 no existe, pero por su forma sería 'Falla de calidad tipo 1'.",
            "QQQ1 no existe en el catálogo; el modo correcto sería XYZ.",
        ],
    )
    def test_un_invento_real_falla(self, texto):
        assert not self._ok(texto), f"se coló: {texto[:60]}"

    def test_negar_no_es_atribuir(self):
        assert V._es_negacion("no está en el catálogo ISO 14224")
        assert V._es_negacion("No existe en el catálogo")
        assert not V._es_negacion("Falla en arrancar cuando es requerido")


class TestLosCodigosDeSalidaNoSeContradicen:
    """La misma avería medida en dos momentos devolvía dos códigos, y el de la
    puerta de entrada era el que significa «el producto falló»."""

    def test_el_proveedor_caido_al_arrancar_no_es_un_fallo_del_producto(self, monkeypatch):
        monkeypatch.setattr(V, "LLAVE", "una-llave")
        monkeypatch.setattr(
            V, "_proveedor_atiende", lambda _c: (False, "no tiene saldo")
        )
        assert V.main() == 2, "una corrida truncada no es un criterio en rojo"

    def test_sin_llave_es_un_error_de_operador(self, monkeypatch):
        monkeypatch.setattr(V, "LLAVE", "")
        assert V.main() == 3


class TestUnHtmlDelBordeNoSeComeElVeredicto:
    """El censo final hacía `.json()` a pelo dentro del `finally`. Un 502 de
    Cloudflare llega como HTML, así que el ValueError salía del finally y se
    comía el `return 2`: el arreglo del código de salida lo anulaba la respuesta
    de un WAF."""

    class _Respuesta:
        status_code = 502

        @staticmethod
        def json():
            raise ValueError("no es JSON")

        @staticmethod
        def raise_for_status():
            pass

    class _Turno:
        status_code = 200

        @staticmethod
        def raise_for_status():
            pass

        @staticmethod
        def json():
            return {"content": "Error code: 400 - your credit balance is too low"}

    class _Sonda:
        status_code = 200

        @staticmethod
        def json():
            return {"detalle": "El proveedor responde."}

    def _cliente(self):
        prueba = self

        class Cliente:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def get(self, url, **k):
                return prueba._Sonda() if "health/modelo" in url else prueba._Respuesta()

            def post(self, *a, **k):
                return prueba._Turno()

            def delete(self, *a, **k):
                return type("R", (), {"status_code": 204})()

        return Cliente

    def test_el_codigo_2_sobrevive_a_un_censo_ilegible(self, monkeypatch):
        monkeypatch.setattr(V, "LLAVE", "una-llave")
        monkeypatch.setattr(V.httpx, "Client", self._cliente())
        assert V.main() == 2, "un 502 del borde se comió el veredicto"

    def test_lo_dice_en_vez_de_callarlo(self, monkeypatch, capsys):
        monkeypatch.setattr(V, "LLAVE", "una-llave")
        monkeypatch.setattr(V.httpx, "Client", self._cliente())
        V.main()
        assert "no se pudo verificar el censo" in capsys.readouterr().out


class TestUnaCorridaTruncadaNoEscondeLoYaMedido:
    """`return 2` se saltaba `_veredicto`, así que un criterio ya medido en rojo
    nunca aparecía en «Fallidos:», y el script llegaba a afirmar por escrito que
    no había fallo del producto cuando ya había medido uno."""

    def _hallazgos(self, con_rojo: bool) -> list[dict]:
        h = [{"criterio": n, "descripcion": f"c{n}", "ok": True, "evidencia": ""}
             for n in V.ESPERADOS[:2]]
        if con_rojo:
            h[0]["ok"] = False
        return h

    def test_los_rojos_medidos_mandan_sobre_la_truncacion(self, capsys):
        # No se puede decir «esto no es un fallo del producto» habiendo medido uno.
        codigo = V._veredicto(self._hallazgos(con_rojo=True), [], [])
        assert codigo == 1
        assert "Fallidos:" in capsys.readouterr().out

    def test_sin_rojos_medidos_el_veredicto_no_los_inventa(self, capsys):
        V._veredicto(self._hallazgos(con_rojo=False), [], [])
        assert "Fallidos:" not in capsys.readouterr().out


class TestLaVerdadDelCriterio29SaleDeLaHerramienta:
    """Tres intentos fallaron por comparar contra palabras clave elegidas a
    mano. El catálogo lo devuelve `explain_iso_code` en la misma corrida."""

    def test_lee_las_definiciones_del_resultado(self):
        salida = {"tools": [{"tool_name": "explain_iso_code", "result": (
            "El código 'QQQ1' no está en el catálogo. Códigos disponibles:\n"
            "- FTS — Falla en arrancar cuando es requerido\n"
            "- STP — Falla para detenerse cuando es requerido"
        )}]}
        reales = V._definiciones_de_la_herramienta(salida)
        assert reales["FTS"] == "Falla en arrancar cuando es requerido"
        assert len(reales) == 2

    def test_sin_llamada_no_inventa_catalogo(self):
        assert V._definiciones_de_la_herramienta({"tools": [{"tool_name": "otra"}]}) == {}

    def test_el_nucleo_reconoce_variantes_de_la_misma_raiz(self):
        # Palabra a palabra, no por la frase entera: con prefijo 5, «falla» y
        # «fallo» ya NO se unen, y el test pasaba solo por «arran» mientras su
        # nombre prometía más.
        assert V._nucleo("arrancar") & V._nucleo("arranque"), "no une la misma raíz"
        assert V._nucleo("vibración") & V._nucleo("vibraciones")
        assert not V._nucleo("arrancar") & V._nucleo("detenerse")


class TestLosCasosQueElValidadorConstruyo:
    """Cinco mutaciones sobrevivían porque estos casos no estaban escritos:
    los reprodujo el validador y aquí quedan fijados."""

    @property
    def _reales(self) -> dict[str, str]:
        from rcm_runbook.models.catalogs import fixture

        return {c.code: c.definition for c in fixture().menu.iso14224_failure_mode_codes}

    def _ok(self, texto: str) -> bool:
        return V._juzgar_codigo_iso(texto, "QQQ1", self._reales)[0]

    def test_un_significado_torcido_sale_a_revision_no_a_veredicto(self):
        """Antes esto era un ❌. Ya no, y el cambio es deliberado.

        Decidirlo exigía trocear la prosa para saber qué definición iba con qué
        código, y cuatro rondas de hacerlo dieron cuatro veredictos distintos
        sobre los mismos textos: la última suspendía «También FOV — …» y
        aprobaba «y FOV — …». Se recoge y lo mira una persona.
        """
        _, _, revisar = V._juzgar_codigo_iso(
            "QQQ1 no existe en el catálogo.\nFTS — Fuga Total del Sistema, "
            "aunque no está confirmado en OREDA.",
            "QQQ1",
            self._reales,
        )
        assert revisar, "no dejó constancia de nada que revisar"
        assert any("FTS" in linea for linea in revisar)

    def test_lo_que_pasa_a_revision_no_tumba_el_veredicto(self):
        assert self._ok(
            "QQQ1 no existe en el catálogo.\n| FTS | Falla en arrancar |\n"
            "| FTS | Fuga Total del Sistema |"
        ), "una contradicción interna no es una sigla fuera del catálogo"

    def test_el_invento_tras_un_punto_se_caza(self):
        assert not self._ok(
            "El código QQQ1 no existe en el catálogo. Por su forma sería "
            "'Falla de Calidad tipo 1'."
        )

    def test_un_sinonimo_legitimo_no_se_reprueba(self):
        assert self._ok("QQQ1 no existe.\n| **FTS** | Fallo al arranque del equipo |")

    def test_negar_un_codigo_real_no_es_inventarlo(self):
        assert self._ok(
            "QQQ1 no existe.\n| **STP** | No aparece en el catálogo de este cliente |"
        )

    def test_abstenerse_tampoco(self):
        assert self._ok(
            "QQQ1 no existe.\nFTS — no se pudo verificar en el catálogo del cliente."
        )

    def test_el_catalogo_lo_pone_la_herramienta(self):
        # El conjunto contra el que se compara son los veinte códigos que
        # devolvió la herramienta en ESTA corrida, no una tabla escrita a mano:
        # si el cliente añade un código, el instrumento lo aprende solo.
        _, _, revisar = V._juzgar_codigo_iso(
            "QQQ1 no existe en el catálogo.\n| **ZZZ** | Fuga |", "QQQ1", self._reales
        )
        assert any("ZZZ" in linea for linea in revisar)
        _, _, limpio = V._juzgar_codigo_iso(
            "QQQ1 no existe en el catálogo.\n| **VIB** | Fuga total |",
            "QQQ1", self._reales,
        )
        assert not any("siglas que el catálogo no tiene" in x for x in limpio)


class TestLosCodigosDeSalidaCubrenLoQueOcurre:
    """0 bien · 1 criterio en rojo · 2 corrida truncada · 3 operador ·
    4 la corrida ensució la base · 5 falló el arnés, no el producto."""

    def _hallazgos(self, ok: bool = True) -> list[dict]:
        return [{"criterio": n, "descripcion": "", "ok": ok, "evidencia": ""}
                for n in V.ESPERADOS]

    def test_la_fuga_manda_sobre_todo_lo_demas(self):
        assert V._codigo_final(1, self._hallazgos(ok=False), True, ["uat-x"]) == 4

    def test_una_truncacion_limpia_sale_dos(self):
        assert V._codigo_final(1, self._hallazgos(), True, []) == 2

    def test_una_truncacion_con_rojos_medidos_sale_uno(self):
        # Los criterios que faltan, faltan POR la truncación; los ya medidos en
        # rojo mandan, y decir «esto no es un fallo del producto» sería falso.
        assert V._codigo_final(1, self._hallazgos(ok=False), True, []) == 1

    def test_una_corrida_completa_devuelve_su_veredicto(self):
        assert V._codigo_final(0, self._hallazgos(), False, []) == 0
        assert V._codigo_final(1, self._hallazgos(ok=False), False, []) == 1



class TestElCriterio29UsaElCatalogoDeLaCorrida:
    """El cableado, no solo la pieza: con una tabla de palabras clave fija, un
    código fuera de esa tabla no se juzgaba."""

    def _salida(self, respuesta: str) -> dict:
        return {
            "content": respuesta,
            "tools": [{"tool_name": "explain_iso_code", "result": (
                "El código 'QQQ1' no está en el catálogo. Códigos disponibles:\n"
                "- FTS — Falla en arrancar cuando es requerido\n"
                "- VIB — Vibración\n"
                "- STP — Falla para detenerse cuando es requerido"
            )}],
        }

    def test_una_sigla_fuera_del_catalogo_de_la_corrida_se_anota(self):
        _, _, revisar = V._evaluar_criterio_29(
            self._salida("QQQ1 no existe en el catálogo.\n| **ZZZ** | Un modo nuevo |"),
            "QQQ1",
        )
        assert any("ZZZ" in linea for linea in revisar)

    def test_aprueba_la_definicion_correcta_del_mismo_codigo(self):
        ok, _, _ = V._evaluar_criterio_29(
            self._salida(
                "QQQ1 no existe en el catálogo.\n| **VIB** | Vibración excesiva |"
            ),
            "QQQ1",
        )
        assert ok

    def test_sin_catalogo_lo_dice_en_vez_de_aprobar(self):
        ok, evidencia, _ = V._evaluar_criterio_29(
            {"content": "QQQ1 no existe en el catálogo. Están FTS, STP y BRD.",
             "tools": []},
            "QQQ1",
        )
        assert not ok and "CATÁLOGO VACÍO" in evidencia


class TestLosDialesDelDetectorEstanFijados:
    """Tres mutaciones sobrevivían porque nada fijaba los números del método: el
    prefijo de comparación y la forma del código. Se podía bajar el prefijo a
    tres —que multiplica las colisiones— con la suite entera en verde."""

    def test_el_prefijo_une_variantes_pero_no_palabras_distintas(self):
        # Cinco: con cuatro, «parámetros» y «parada» colisionaban y eso absolvía
        # atribuirle «Parada inesperada» al código de desviación de parámetros.
        assert V._nucleo("arrancar") & V._nucleo("arranque"), "no une la misma raíz"
        assert not V._nucleo("parametros") & V._nucleo("parada"), "colisiona"

    def test_ignora_acentos_como_el_resto_del_modulo(self):
        # `_es_negacion` normalizaba y `_nucleo` no: dos criterios en el mismo
        # módulo, y «Pérdida» no casaba con «Perdida».
        assert V._nucleo("Pérdida de caudal") & V._nucleo("perdida total")

    def test_lee_los_dos_formatos_de_la_herramienta(self):
        # La rama de éxito no lleva guion inicial, y exigirlo dejaba el catálogo
        # vacío y el criterio declarándose «nada que juzgar».
        con_guion = {"tools": [{"tool_name": "explain_iso_code", "result":
                                "- FTS — Falla en arrancar cuando es requerido"}]}
        sin_guion = {"tools": [{"tool_name": "explain_iso_code", "result":
                                "FTS — Falla en arrancar: Incapaz de arrancar"}]}
        assert V._definiciones_de_la_herramienta(con_guion)
        assert V._definiciones_de_la_herramienta(sin_guion), "el formato de éxito no se lee"

    def test_desconocido_no_absuelve_al_codigo_UNK(self):
        # «desconocido» es la definición literal de UNK: listarla como negación
        # hacía que atribuirle cualquier cosa se saltara la comprobación.
        assert not V._es_negacion("Desconocido: fuga masiva de crudo")

    def test_el_patron_del_codigo_cubre_el_catalogo_y_nada_mas(self):
        # Con seis letras, «OREDA» —que aparece en estas mismas respuestas como
        # fuente de datos— se leería como un código del catálogo.
        from rcm_runbook.models.catalogs import fixture

        salida = {"tools": [{"tool_name": "explain_iso_code", "result": "\n".join(
            f"- {c.code} — {c.definition}"
            for c in fixture().menu.iso14224_failure_mode_codes
        ) + "\n- OREDA — base de datos de confiabilidad"}]}
        leidos = V._definiciones_de_la_herramienta(salida)
        del_catalogo = {c.code for c in fixture().menu.iso14224_failure_mode_codes}
        assert del_catalogo <= set(leidos), "no lee todos los códigos del cliente"
        assert "OREDA" not in leidos, "leyó una fuente de datos como código ISO"

    def test_el_patron_tambien_tiene_suelo(self):
        # El techo estaba fijado (OREDA, cinco letras) y el suelo no: con dos,
        # cualquier par de mayúsculas seguido de raya entra como código ISO.
        salida = {"tools": [{"tool_name": "explain_iso_code", "result":
                             "- FTS — Falla en arrancar cuando es requerido\n"
                             "- SI — Sistema Internacional de unidades"}]}
        leidos = V._definiciones_de_la_herramienta(salida)
        assert "FTS" in leidos
        assert "SI" not in leidos, "leyó un par de mayúsculas como código ISO"

    def test_las_palabras_cortas_no_ensucian_la_comparacion(self):
        # Con el mínimo en tres, «uso», «fin» o «mal» entran en el núcleo y
        # emparejan definiciones que no tienen nada que ver.
        assert V._nucleo("uso fin mal") == set()
        assert V._nucleo("fuga externa") == {"fuga", "exter"}


class TestElCatalogoSeLeeEntero:
    """`_definiciones_de_la_herramienta` devolvía en la PRIMERA llamada. Si esa
    era la rama de éxito —un solo código—, el catálogo quedaba con un elemento y
    el detector no podía acusar nada por construcción, mientras la evidencia
    decía «definidos: ['FTS']», que se lee como una medición."""

    def _salida(self) -> dict:
        return {
            "content": "QQQ1 no existe. FTS — Fuga Total del Sistema. HIO — Baja salida.",
            "tools": [
                {"tool_name": "explain_iso_code",
                 "result": "FTS — Falla en arrancar: Incapaz de activar la bomba"},
                {"tool_name": "explain_iso_code", "result":
                 "El código 'QQQ1' no está en el catálogo. Códigos disponibles:\n"
                 "- FTS — Falla en arrancar cuando es requerido: Incapaz de arrancar\n"
                 "- HIO — Alta Salida: Presion de salida fuera de especificacion\n"
                 "- ELU — Fuga Externa de Utilidades: Fuga de aceite o agua"},
            ],
        }

    def test_junta_todas_las_llamadas(self):
        catalogo = V._definiciones_de_la_herramienta(self._salida())
        assert set(catalogo) == {"FTS", "HIO", "ELU"}, (
            f"se quedó con la primera llamada: {catalogo}"
        )

    def test_y_el_catalogo_entero_llega_a_la_revision_humana(self):
        _, _, revisar = V._evaluar_criterio_29(self._salida(), "QQQ1")
        assert revisar, "no dejó nada anotado para revisar"

    def test_lo_que_se_manda_a_revisar_nombra_el_codigo_con_el_que_encaja(self):
        # El operador leía «encaja con STD» sin saber qué es STD. Es justo lo
        # que `explain_iso_code` dejó de hacer a propósito.
        _, _, revisar = V._evaluar_criterio_29(self._salida(), "QQQ1")
        texto = " ".join(revisar)
        assert "encaja con" in texto
        assert ":" in texto.split("encaja con")[1][:60], "la sigla va pelada"


class TestElDetectorMideConLaMismaVara:
    """`propio` se medía contra la definición corta (dos o tres palabras) y los
    rivales sumaban sobre veinte definiciones: bastaba una palabra genérica
    compartida para acusar. Reprobaba hasta una cita literal del catálogo."""

    @property
    def _reales(self) -> dict[str, str]:
        from rcm_runbook.models.catalogs import fixture

        return {
            c.code: f"{c.definition}: {c.description}"
            for c in fixture().menu.iso14224_failure_mode_codes
        }

    @pytest.mark.parametrize(
        "atribucion",
        [
            "BRD — Daño Grave (Obstruccion, Rotura, Fractura, Explosion etc.)",
            "SER — Perdida de elementos, descoloracion, sucio, etc.",
            "HIO — Presión de descarga por encima del rango de proceso",
            "OHE — Temperatura excesiva en el proceso",
            "INL — Aceite lubricante hacia el medio del proceso",
        ],
    )
    def test_una_definicion_correcta_no_se_acusa(self, atribucion):
        _, inventados = V._codigos_definidos(atribucion, self._reales)
        assert not inventados, f"acusó una respuesta correcta: {inventados}"

    @pytest.mark.parametrize(
        "atribucion",
        [
            "HIO — Baja salida",
            "FTS — Falla para detenerse cuando es requerido",
            "PDE — Parada inesperada del equipo",
        ],
    )
    def test_una_inversion_si_se_acusa(self, atribucion):
        _, inventados = V._codigos_definidos(atribucion, self._reales)
        assert inventados, f"la inversión se coló: {atribucion}"

    def test_la_herramienta_da_definicion_y_descripcion(self):
        # La asimetría nacía en la herramienta: daba la definición corta y se
        # guardaba la descripción, que es con la que el agente parafrasea.
        from rcm_runbook.agent import tools as tools_mod

        class Ctx:
            session_id = "s-iso"
            session_state: dict = {}

        salida = tools_mod.explain_iso_code.entrypoint(Ctx(), code="QQQ1")
        assert "- FTS — Falla en arrancar cuando es requerido:" in salida, (
            "la lista de códigos no lleva la descripción"
        )


class TestElCaminoRealDeLaHerramientaAlDetector:
    """`TestElDetectorMideConLaMismaVara` construía el catálogo A MANO desde el
    fixture, saltándose el regex: el camino real herramienta → `reales` →
    detector no lo probaba nadie. Bajar el tope de lectura a 40 caracteres
    dejaba la suite entera en verde y devolvía el falso positivo de la ronda 17."""

    def _salida_de_la_herramienta(self) -> dict:
        from rcm_runbook.agent import tools as tools_mod

        class Ctx:
            session_id = "s-cam"
            session_state: dict = {}

        # La salida REAL de la herramienta, no una reconstrucción.
        return {
            "content": "",
            "tools": [{"tool_name": "explain_iso_code",
                       "result": tools_mod.explain_iso_code.entrypoint(Ctx(), code="QQQ1")}],
        }

    def test_la_descripcion_llega_entera_hasta_el_detector(self):
        catalogo = V._definiciones_de_la_herramienta(self._salida_de_la_herramienta())
        from rcm_runbook.models.catalogs import fixture

        for c in fixture().menu.iso14224_failure_mode_codes:
            leido = catalogo.get(c.code, "")
            assert c.definition in leido, f"{c.code}: falta la definición"
            assert c.description[:20] in leido, (
                f"{c.code}: la descripción llegó truncada — «{leido}»"
            )

    def test_el_eco_literal_de_la_herramienta_no_se_acusa(self):
        # Lo más correcto que puede hacer el agente: repetir la lista que le
        # acaban de dar. Se acusaba a UST de describir a BRD.
        salida = self._salida_de_la_herramienta()
        texto = str(salida["tools"][0]["result"])
        catalogo = V._definiciones_de_la_herramienta(salida)
        _, inventados = V._codigos_definidos(texto, catalogo)
        assert not inventados, f"acusó la cita literal de la herramienta: {inventados}"

    def test_y_aun_asi_caza_una_inversion_en_esa_misma_lista(self):
        # La inversión se construye DESDE el catálogo leído, no desde una
        # cadena literal: un `.replace()` con el texto del fixture escrito a
        # mano se vuelve un no-op silencioso en cuanto el cliente corrija una
        # mayúscula, y el test se pone rojo sin que el detector haya empeorado.
        salida = self._salida_de_la_herramienta()
        catalogo = V._definiciones_de_la_herramienta(salida)
        texto = str(salida["tools"][0]["result"])
        victima, ladron = sorted(catalogo)[0], sorted(catalogo)[1]
        texto = re.sub(
            rf"({victima}\s*—\s*)[^\n]+", rf"\1{catalogo[ladron]}", texto, count=1
        )
        _, inventados = V._codigos_definidos(texto, catalogo)
        assert inventados, "la inversión dentro de la lista pasó desapercibida"

    def test_dos_codigos_en_la_misma_linea_no_se_acusan(self):
        # El corte por fin de línea suponía «una línea, un código». En una fila
        # de tabla o un párrafo corrido el vecino vuelve a colarse, y como las
        # palabras coladas son las suyas, el vecino gana igual que en la r19.
        catalogo = V._definiciones_de_la_herramienta(self._salida_de_la_herramienta())
        codigos = sorted(catalogo)
        for a, b in zip(codigos, codigos[1:], strict=False):
            for plantilla in (
                "**{a}** — {da}. **{b}** — {db}.",
                "| {a} | {da} | {b} | {db} |",
                "{a} significa {da} y {b} significa {db}",
            ):
                texto = plantilla.format(a=a, b=b, da=catalogo[a], db=catalogo[b])
                _, inventados = V._codigos_definidos(texto, catalogo)
                assert not inventados, f"acusó el eco literal de {a} y {b}: {inventados}"

    def test_el_catalogo_entero_en_un_solo_parrafo_no_se_acusa(self):
        catalogo = V._definiciones_de_la_herramienta(self._salida_de_la_herramienta())
        texto = " ".join(f"{c} — {d}." for c, d in catalogo.items())
        _, inventados = V._codigos_definidos(texto, catalogo)
        assert not inventados, f"acusó el catálogo entero en un párrafo: {inventados}"

    def test_una_definicion_envuelta_al_renglon_siguiente_se_juzga(self):
        # Con el corte por línea el tramo quedaba en «—»: pasaba el filtro de
        # separador, así que se listaba como definido, pero no había núcleo que
        # comparar y la inversión no se comprobaba. Un descarte silencioso.
        catalogo = V._definiciones_de_la_herramienta(self._salida_de_la_herramienta())
        victima, ladron = sorted(catalogo)[0], sorted(catalogo)[1]
        texto = f"- {victima} —\n  {catalogo[ladron]}"
        definidos, inventados = V._codigos_definidos(texto, catalogo)
        assert inventados, f"la inversión envuelta no se cazó (definidos: {definidos})"

    def test_un_codigo_sin_nada_detras_no_se_cuenta_como_juzgado(self):
        catalogo = V._definiciones_de_la_herramienta(self._salida_de_la_herramienta())
        victima = sorted(catalogo)[0]
        definidos, _ = V._codigos_definidos(f"- {victima} —\n", catalogo)
        assert victima not in definidos, "dijo haber juzgado un código sin definición"

    def test_un_solo_codigo_no_se_lleva_el_discurso_que_le_sigue(self):
        # Sin tope por arriba, un código mencionado una vez y seguido de un
        # párrafo largo se queda con el párrafo entero como «lo que atribuyó»:
        # basta que el agente hable después de otra cosa para que el detector
        # encuentre ahí las palabras de otro código y acuse.
        catalogo = V._definiciones_de_la_herramienta(self._salida_de_la_herramienta())
        victima, ajeno = sorted(catalogo)[0], sorted(catalogo)[1]
        texto = (
            f"- {victima} — {catalogo[victima]}\n\n"
            + "Conviene revisar el histórico del equipo antes de decidir. " * 4
            + catalogo[ajeno]
        )
        _, inventados = V._codigos_definidos(texto, catalogo)
        assert not inventados, f"se llevó el discurso posterior: {inventados}"

    def test_una_palabra_que_contiene_un_codigo_no_corta_el_tramo(self):
        # `AIR` vive dentro de «AIRE» y `SER` dentro de «SERVICIO», dos palabras
        # que aparecen en mayúsculas en cualquier texto de mantenimiento. Sin
        # frontera de palabra el tramo se corta ahí, la atribución queda
        # mutilada y una inversión real deja de compararse.
        catalogo = V._definiciones_de_la_herramienta(self._salida_de_la_herramienta())
        victima = sorted(catalogo)[0]
        texto = f"- {victima} — falla del compresor de AIRE de instrumentos SERVICIO"
        tramo = V._tramo_tras(texto, texto.index(victima) + len(victima), catalogo)
        assert tramo.strip().endswith("SERVICIO"), f"el tramo llegó cortado: «{tramo}»"

    def test_el_tope_del_tramo_deja_holgura_sobre_el_catalogo_del_cliente(self):
        # El tope es un dial y el catálogo es del cliente: va a crecer. Sin este
        # test, «sin tope» y «el largo exacto de hoy» sobreviven los dos.
        catalogo = V._definiciones_de_la_herramienta(self._salida_de_la_herramienta())
        mas_larga = max(catalogo.values(), key=len)
        holgado = f"{sorted(catalogo)[0]} — {mas_larga} {'x' * 20}"
        tramo = V._tramo_tras(holgado, holgado.index(" "), catalogo)
        assert tramo.endswith("x" * 20), (
            f"una entrada 20 caracteres más larga que la de hoy se trunca: «{tramo}»"
        )

class TestLosDialesDeLaNegacion:
    """Al quitar la ventana inerte quedó sin fijar el criterio: recortar a 20
    caracteres convierte una abstención legítima en acusación."""

    def test_una_abstencion_en_el_limite_del_tramo_se_reconoce(self):
        # 60 caracteres es lo máximo que capturan los patrones de
        # `_significado_atribuido`, el único llamador. La marca de negación al
        # final de ese máximo es el peor caso real, y es lo que fija el dial.
        texto = "explain_iso_code consultado y revisado, sin resultados"
        assert len(texto) <= 60 and texto.index("sin resultados") > 30
        assert V._es_negacion(texto)

    def test_y_una_corta_tambien(self):
        assert V._es_negacion("no existe")

    def test_una_definicion_de_verdad_no_es_negacion(self):
        assert not V._es_negacion("Falla en arrancar cuando es requerido")

    def test_una_definicion_larga_se_compara_entera(self):
        # El tope del tramo es un dial: recortarlo parte las definiciones largas
        # del catálogo y las deja sin las palabras que las distinguen.
        from rcm_runbook.models.catalogs import fixture

        codigos = fixture().menu.iso14224_failure_mode_codes
        mas_larga = max(codigos, key=lambda c: len(f"{c.definition}: {c.description}"))
        reales = {c.code: f"{c.definition}: {c.description}" for c in codigos}
        linea = f"- {mas_larga.code} — {mas_larga.definition}: {mas_larga.description}"
        tramo = V._tramo_tras(
            linea, linea.index(mas_larga.code) + len(mas_larga.code), reales
        )
        assert mas_larga.description[-12:] in tramo, (
            f"la definición más larga del catálogo llega cortada: «{tramo}»"
        )


class TestElCriterio40NoSeMideSolo:
    """El medidor del 40 se retiró, y esto fija que siga retirado.

    Tuvo dos varas seguidas y las dos fallaron en direcciones opuestas: por
    subcadena literal rechazaba «exploración de LA edad»; por raíces aprobaba en
    verde una respuesta que negaba los cuatro conceptos («aquí no hay problema
    de seguridad… no es un asunto de calidad»). El criterio se pregunta a pelo,
    sin herramientas, así que no hay nada contra qué contrastar salvo el texto.
    Un ✅ fabricado así vale menos que un «lo mira una persona».
    """

    def test_no_queda_ningun_medidor_del_40(self):
        for nombre in ("_conceptos_que_faltan", "_veredicto_criterio_40",
                       "CONCEPTOS_DE_LAS_SIGLAS"):
            assert not hasattr(V, nombre), (
                f"{nombre} volvió: si se vuelve a puntuar el 40, que sea con "
                "una decisión explícita y no dejando código muerto encendido"
            )

    def test_el_40_esta_declarado_como_revision_humana(self):
        assert 40 in V.REQUIEREN_OJO and 40 not in V.ESPERADOS


class TestLaReferenciaCruzadaNoAbsuelveLaInversion:
    """El corte de la ronda 20 paraba en toda aparición de cualquier código,
    así que mencionar otro código dentro de la explicación dejaba el tramo en un
    muñón y la inversión salía en verde. Y el muñón traía palabras de relleno de
    cuatro letras, así que el guardián `_nucleo` lo daba por juzgado: el
    descarte silencioso nº 17."""

    # Catálogo SINTÉTICO y con definiciones deliberadamente disjuntas, no el
    # del cliente. Contra el fixture, este test se rompía en cuanto el cliente
    # diera de alta un código parecido a otro —`LOP` junto a `LOO`, `OVH` junto
    # a `OHE`— sin que el detector hubiera empeorado; y encima contradecía lo
    # que `_describe_mejor_a_otro` promete: cuando dos definiciones son
    # indistinguibles, se dice y no se acusa.
    REALES = {
        "AAA": "Falla en arrancar: el equipo no entrega giro al recibir la orden",
        "BBB": "Fuga externa de fluido: derrame visible por la junta del eje",
        "CCC": "Vibración excesiva: amplitud por encima del umbral admisible",
        "DDD": "Temperatura elevada: sobrecalentamiento del devanado del motor",
    }

    @pytest.mark.parametrize(
        "plantilla",
        [
            "- {a} — {db}",
            "- {a} — {a}: {db}",
            "- {a} — igual que {b}: {db}",
            "- {a} — a diferencia de {b}, {db}",
            "- {a} — (ver {b}) {db}",
            "- {a} — en el TAG P-101-{b} se ve: {db}",
        ],
    )
    def test_la_inversion_se_recoge_en_todos_los_pares(self, plantilla):
        reales = self.REALES
        ciegos = [
            (a, b)
            for a in reales
            for b in reales
            if a != b
            and not V._codigos_definidos(
                plantilla.format(a=a, b=b, db=reales[b]), reales
            )[1]
        ]
        assert not ciegos, f"{len(ciegos)} pares sin recoger, p.ej. {ciegos[:3]}"

    def test_dos_definiciones_indistinguibles_no_se_acusan(self):
        # Lo que el propio `_describe_mejor_a_otro` promete, y que el test
        # anterior exigía romper: si el cliente da de alta un código cuya
        # definición es casi la de otro, callar es lo correcto.
        reales = {**self.REALES,
                  "AAB": "Falla en arrancar: el equipo no entrega giro al recibir la orden"}
        _, sospechas = V._codigos_definidos(f"- AAA — {reales['AAB']}", reales)
        assert not sospechas, f"acusó con dos definiciones idénticas: {sospechas}"

    def test_el_codigo_repetido_en_su_propia_definicion_no_vacia_el_tramo(self):
        reales = self.REALES
        texto = "- **AAA** — el modo AAA describe una fuga externa de fluido"
        tramo = V._tramo_tras(texto, texto.index("AAA") + 3, reales, "AAA")
        assert "fuga externa" in tramo, f"el tramo quedó en un muñón: «{tramo}»"

    def test_un_relleno_de_cuatro_letras_no_cuenta_como_juzgado(self):
        # `_nucleo(" — el modo ")` = {"modo"}: no vacío, así que pasaba por
        # «definido» mientras la inversión no se comprobaba.
        reales = self.REALES
        _, inventados = V._codigos_definidos(
            f"- AAA — el modo AAA describe: {reales['BBB']}", reales
        )
        assert inventados, "el muñón con relleno absolvió la inversión"

    def test_el_eco_literal_sigue_sin_acusarse_en_los_cinco_formatos(self):
        reales = self.REALES
        for formato in (
            "\n".join(f"- {c} — {d}" for c, d in reales.items()),
            " ".join(f"**{c}** — {d}." for c, d in reales.items()),
            " ".join(f"| {c} | {d} |" for c, d in reales.items()),
            " ".join(f"{c} — {d}." for c, d in reales.items()),
            ", ".join(f"{c} — {d}" for c, d in reales.items()),
        ):
            _, inventados = V._codigos_definidos(formato, reales)
            assert not inventados, f"acusó el eco literal: {inventados}"


class TestLosBordesDelCorteEstanFijados:
    """Tres mutantes sobrevivieron la ronda 21 entera: el borde del corte, la
    exclusión del propio código y el requisito de separador. Un mutante vivo no
    es un éxito, es un sitio donde el instrumento puede romperse sin que nadie
    se entere."""

    @property
    def REALES(self) -> dict[str, str]:  # noqa: N802
        from rcm_runbook.models.catalogs import fixture

        return {
            c.code: f"{c.definition}: {c.description}"
            for c in fixture().menu.iso14224_failure_mode_codes
        }

    def test_el_corte_no_se_lleva_las_letras_del_codigo_siguiente(self):
        # `fin = m.end()` en vez de `m.start()` mete la sigla del vecino en el
        # tramo. Con códigos de tres letras `_nucleo` las descarta por cortas y
        # no se nota; el regex del catálogo acepta CUATRO, así que el catálogo
        # del cliente puede traerlas y entonces sí pesan en la comparación.
        reales = dict(self.REALES)
        reales["FTSX"] = "Fuga total del sistema: derrame externo continuo"
        texto = f"- STP — {reales['STP']}. FTSX — Fuga total del sistema"
        tramo = V._tramo_tras(texto, texto.index("STP") + 3, reales, "STP")
        assert "FTSX" not in tramo, f"el tramo se llevó la sigla vecina: «{tramo}»"

    def test_un_codigo_repetido_dentro_de_su_definicion_no_vacia_el_tramo(self):
        # Sin excluir el propio código, «FTS — FTS: <definición de STP>» dejaba
        # el tramo en «— » y la inversión salía en verde.
        reales = self.REALES
        texto = f"- FTS — FTS: {reales['STP']}"
        assert V._codigos_definidos(texto, reales)[1], "la inversión salió absuelta"

    def test_la_exclusion_del_propio_codigo_cambia_el_tramo_no_el_fallo(self):
        """Por qué la exclusión se queda aunque el veredicto no la necesite.

        Quitarla deja el primer tramo en un muñón, pero `_codigos_definidos`
        recorre TODAS las apariciones del código y la segunda trae la
        atribución entera: la acusación sale igual por el otro camino. O sea
        que el veredicto no distingue las dos ramas —por eso el mutante
        sobrevivía— pero el TRAMO sí, y de él sale la evidencia que se imprime.
        Este test fija esa diferencia; si un día deja de haberla, el caso ya no
        demuestra nada y hay que buscar otro.
        """
        reales = self.REALES

        def sin_exclusion(texto: str, desde: int) -> str:
            resto = texto[desde:]
            fin = len(resto)
            for otro in reales:
                for m in re.finditer(rf"\b{otro}\b", resto):
                    if m.start() >= fin:
                        break
                    if V._abre_otra_atribucion(resto, m):
                        fin = m.start()
                        break
            return resto[:fin][:120]

        # «- FTS — <def>, ver FTS» NO sirve: «ver» no abre atribución en
        # ninguna de las dos ramas, así que el tramo sale idéntico y el caso no
        # demuestra nada.
        for plantilla in ("- {a} — {a}: {db}", "- {a} — {a} significa {db}"):
            texto = plantilla.format(a="FTS", db=reales["STP"])
            i = texto.index("FTS") + 3
            distinto = V._tramo_tras(texto, i, reales, "FTS") != sin_exclusion(texto, i)
            acusa = bool(V._codigos_definidos(texto, reales)[1])
            assert distinto and acusa, (
                f"«{plantilla}» ya no demuestra la equivalencia: el tramo no "
                "cambia, o el veredicto dejó de acusar"
            )

    def test_una_preposicion_de_una_letra_no_abre_atribucion(self):
        # La excepción de conjunción es `[yeou]`, no «cualquier palabra de una
        # letra»: «similar A STP: …» es una referencia cruzada, igual que «que»
        # o «de», y ensancharla a `[a-z]` deja de cazar la inversión.
        reales = self.REALES
        texto = f"- FTS — similar a STP: {reales['STP']}"
        assert V._codigos_definidos(texto, reales)[1], "la referencia cruzada absolvió"

    def test_una_mencion_sin_separador_no_corta_la_definicion(self):
        # Sin exigir separador detrás, un paréntesis aclaratorio justo tras el
        # guion cortaba el tramo en seco y el código dejaba de juzgarse.
        reales = self.REALES
        texto = f"- FTS — (STP no aplica aquí) {reales['FTS']}"
        definidos, inventados = V._codigos_definidos(texto, reales)
        assert "FTS" in definidos, "el paréntesis se llevó la definición entera"
        assert not inventados, f"y encima acusó: {inventados}"


class TestElCatalogoNoSeApagaPorLaTipografia:
    """El catálogo se leía solo con raya larga `—`. Con guion ASCII, dos puntos,
    barra de tabla o el código en negrita salía VACÍO, y el criterio se declaraba
    sin nada que comprobar mientras la respuesta se inventaba códigos: descarte
    silencioso nº 18. Que un cambio de tipografía en la herramienta apague el
    instrumento sin decir nada es la avería que más veces ha vuelto aquí."""

    @pytest.mark.parametrize(
        "linea",
        [
            "- FTS — Falla en arrancar cuando es requerido",
            "FTS — Falla en arrancar cuando es requerido",
            "- FTS – Falla en arrancar cuando es requerido",
            "- FTS - Falla en arrancar cuando es requerido",
            "- FTS: Falla en arrancar cuando es requerido",
            "- **FTS** — Falla en arrancar cuando es requerido",
            "| FTS | Falla en arrancar cuando es requerido |",
            "* FTS — Falla en arrancar cuando es requerido",
            "> FTS — Falla en arrancar cuando es requerido",
        ],
    )
    def test_lo_lee_con_cualquier_separador(self, linea):
        catalogo = V._definiciones_de_la_herramienta(
            {"tools": [{"tool_name": "explain_iso_code", "result": linea}]}
        )
        assert "FTS" in catalogo, f"el catálogo quedó vacío con «{linea}»"
        assert "arrancar" in catalogo["FTS"]

    def test_y_la_salida_real_de_la_herramienta_sigue_leyendose_entera(self):
        from rcm_runbook.agent import tools as tools_mod
        from rcm_runbook.models.catalogs import fixture

        class Ctx:
            session_id = "s-tip"
            session_state: dict = {}

        salida = {"tools": [{"tool_name": "explain_iso_code",
                             "result": tools_mod.explain_iso_code.entrypoint(
                                 Ctx(), code="QQQ1")}]}
        catalogo = V._definiciones_de_la_herramienta(salida)
        del_cliente = {c.code for c in fixture().menu.iso14224_failure_mode_codes}
        assert set(catalogo) == del_cliente, (
            f"faltan {del_cliente - set(catalogo)} o sobran {set(catalogo) - del_cliente}"
        )


class TestLoQueHayQueRevisarSeImprime:
    """Un 👁 sin nada debajo es peor que nada: dice que hay algo que mirar y no
    enseña qué. Y las líneas del 29 salían indentadas bajo el encabezado del 40,
    o sea colgadas del criterio equivocado."""

    def _hallazgo(self, ok: bool = True) -> list[dict]:
        return [{"criterio": n, "descripcion": f"c{n}", "ok": ok, "evidencia": ""}
                for n in V.ESPERADOS]

    def test_las_lineas_pendientes_salen_en_la_salida(self, capsys):
        V._veredicto(self._hallazgo(), [], [],
                     ["[29] posible inversión: FTS→«Falla para detenerse»"])
        salida = capsys.readouterr().out
        assert "posible inversión" in salida, "prometió revisión y no enseñó nada"
        assert "FTS" in salida

    def test_dice_cuantos_puntos_hay_y_que_no_los_juzga(self, capsys):
        V._veredicto(self._hallazgo(), [], [], ["[29] a", "[40] b"])
        salida = capsys.readouterr().out
        assert "2 puntos" in salida
        assert "NO los juzga" in salida, (
            "sin decirlo, un 0 con cosas pendientes se lee como aprobado limpio"
        )

    def test_sin_pendientes_no_promete_una_lista_vacia(self, capsys):
        V._veredicto(self._hallazgo(), [], [], [])
        assert "puntos para revisar" not in capsys.readouterr().out
