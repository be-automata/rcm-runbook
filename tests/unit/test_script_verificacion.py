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
