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
import json
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
        assert "Ana" in json.dumps(sesion), "el caso que engañaba a la versión vieja"

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

    def test_los_obligatorios_no_dependen_del_modelo(self):
        # 8 y 27 dependen de que el agente llame a export_excel; 26 no se
        # ejecuta. Ninguno puede ser obligatorio.
        assert 8 not in V.ESPERADOS
        assert 27 not in V.ESPERADOS
        assert 26 not in V.ESPERADOS

    def test_los_condicionales_estan_declarados_y_no_se_solapan(self):
        assert set(V.CONDICIONALES) == {8, 27}
        assert not set(V.CONDICIONALES) & set(V.ESPERADOS)

    def test_estan_los_criterios_que_el_guion_promete(self):
        # Los once del guion menos los tres condicionales/no ejecutados.
        del_guion = {1, 4, 8, 10, 23, 25, 26, 27, 29, 36, 40}
        assert set(V.ESPERADOS) == del_guion - {8, 26, 27}


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

    REALES = {"FTS": "arrancar", "STP": "detener", "HIO": "alta", "LOO": "baja"}

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
        assert len(inventados) == 2
        assert "Fuga total" in inventados[0], "no dice QUÉ inventó"

    def test_caza_el_inventado_entre_correctos(self):
        texto = "- **FTS** — Falla en arrancar\n- **HIO** — Exceso de calor"
        definidos, inventados = V._codigos_definidos(texto, self.REALES)
        assert definidos == ["FTS", "HIO"]
        assert [i.split("→")[0] for i in inventados] == ["HIO"]


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

    def test_un_condicional_ausente_no_falla(self):
        assert V._veredicto(self._todos_verdes(), [], []) == 0

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

    REALES = {"FTS": "arrancar", "STP": "detener"}

    def test_tabla_markdown_correcta(self):
        texto = ("| **FTS** | Falla en arrancar cuando es requerido |\n"
                 "| **STP** | Falla para detenerse |")
        definidos, inventados = V._codigos_definidos(texto, self.REALES)
        assert definidos == ["FTS", "STP"] and inventados == []

    def test_tabla_markdown_con_invento(self):
        texto = "| **FTS** | Fuga total del sistema |\n| **STP** | Obstrucción |"
        _, inventados = V._codigos_definidos(texto, self.REALES)
        assert len(inventados) == 2, "el formato que usa de verdad se colaba"

    def test_parentesis_y_verbos(self):
        for texto in ("El código FTS (Fuga Total del Sistema) es común.",
                      "FTS significa Fuga total del sistema."):
            _, inventados = V._codigos_definidos(texto, self.REALES)
            assert inventados, f"se coló: {texto}"


class TestElCriterio29Entero:
    """Ensamblado, no solo sus piezas: la comprobación del código preguntado
    estaba escrita y desconectarla no rompía nada."""

    REALES = {"FTS": "arrancar", "STP": "detener"}

    def _juzgar(self, texto: str):
        return V._juzgar_codigo_iso(texto, "QQQ1", self.REALES)

    def test_respuesta_correcta_aprueba(self):
        ok, _ = self._juzgar(
            "El código **'QQQ1' no existe en el catálogo ISO 14224**.\n"
            "| **FTS** | Falla en arrancar cuando es requerido |"
        )
        assert ok

    def test_inventar_el_significado_del_preguntado_falla(self):
        ok, evidencia = self._juzgar(
            "QQQ1 no existe, pero por su forma sería 'Falla de calidad tipo 1'."
        )
        assert not ok
        assert "QQQ1" in evidencia and "Falla de calidad" in evidencia

    def test_inventar_el_significado_de_uno_real_falla(self):
        ok, _ = self._juzgar(
            "'QQQ1' no existe. | **FTS** | Fuga total del sistema |"
        )
        assert not ok

    def test_no_decir_que_falta_falla(self):
        ok, _ = self._juzgar("| **FTS** | Falla en arrancar cuando es requerido |")
        assert not ok, "no dijo que el código preguntado no está en el catálogo"


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
