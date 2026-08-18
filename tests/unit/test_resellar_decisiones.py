"""Re-sellado de las decisiones ya guardadas, sobre el estado real de la UAT.

Spec: `specs/hash-de-decision-y-de-valoracion.md` (tareas 4 y 5, criterios 1, 2,
6 y 8).

Corre sobre `tests/fixtures/uat_sesion_real.json` —copiado a un temporal; el
fixture no se toca— porque es el único estado donde el defecto existe: 32
decisiones, 4 de ellas con firma humana, y 60 valoraciones frescas que el
reporte contaba como obsoletas.

`bloqueadores_uat_antes.txt` son los 121 bloqueadores que ese estado producía
ANTES de esta feature, congelados. Sin ellos, «bajó a 59» no dice si se fue algo
que no debía irse.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from rcm_runbook.engine.compliance import export_blockers
from rcm_runbook.models.session import RCMSession

RAIZ = Path(__file__).resolve().parents[2]
GUION = RAIZ / "scripts" / "resellar_decisiones.py"
FIXTURE = RAIZ / "tests" / "fixtures" / "uat_sesion_real.json"
BLOQUEADORES_ANTES = RAIZ / "tests" / "fixtures" / "bloqueadores_uat_antes.txt"

_spec = importlib.util.spec_from_file_location("resellar_decisiones", GUION)
assert _spec and _spec.loader
resellar_decisiones = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(resellar_decisiones)


@pytest.fixture
def estado(tmp_path: Path) -> Path:
    destino = tmp_path / "uat.json"
    shutil.copy(FIXTURE, destino)
    return destino


def _leer(ruta: Path) -> dict:
    return json.loads(ruta.read_text("utf-8"))


def _sesion(ruta: Path) -> RCMSession:
    return RCMSession.model_validate(_leer(ruta))


class TestElReSelladoNoCambiaElAnalisis:
    def test_corre_verde_y_deja_cero_decisiones_obsoletas(self, estado, capsys):
        assert resellar_decisiones.procesar(estado) == 0
        # NO `stale_decisions() == []`: esa es la comparación tolerante, y ya
        # daba `[]` ANTES de correr el guion (ver
        # `test_sin_resellar_no_queda_ninguna_desfasada`). Además `procesar`
        # sólo devuelve 0 si su propia verificación estricta pasó, así que
        # afirmarlo después sería afirmar su conclusión. Lo que sí prueba algo
        # es el sello canónico, medido desde fuera del guion.
        sesion = _sesion(estado)
        assert sesion.decisiones_sin_sello_canonico() == []
        assert "ninguna política cambió" in capsys.readouterr().out

    def test_criterio_1_ninguna_politica_cambia(self, estado):
        antes = _leer(FIXTURE)["decisions"]
        resellar_decisiones.procesar(estado)
        despues = _leer(estado)["decisions"]
        assert set(despues) == set(antes) and len(despues) == 32
        for fmid, decision in antes.items():
            for campo in resellar_decisiones.CAMPOS_INTOCABLES:
                assert despues[fmid][campo] == decision[campo], f"{fmid}.{campo}"

    def test_criterio_2_ninguna_firma_se_pierde(self, estado):
        antes = _leer(FIXTURE)
        firmados_antes = {
            fmid for fmid, d in antes["decisions"].items() if d["hitl_confirmed_by"]
        }
        assert len(firmados_antes) == 4
        resellar_decisiones.procesar(estado)
        despues = _leer(estado)
        assert {
            fmid for fmid, d in despues["decisions"].items() if d["hitl_confirmed_by"]
        } == firmados_antes
        assert despues["hitl_ledger"] == antes["hitl_ledger"]

    def test_las_valoraciones_no_se_tocan(self, estado):
        antes = _leer(FIXTURE)
        resellar_decisiones.procesar(estado)
        despues = _leer(estado)
        assert despues["risk_scores"] == antes["risk_scores"]
        assert despues["residual_scores"] == antes["residual_scores"]
        assert _sesion(estado).stale_scores() == []

    def test_se_resellan_las_32_incluida_la_que_hoy_esta_fresca(self, estado):
        """FM-019 es la única decisión no obsoleta hoy, y su sello viejo SÍ
        llevaba su control dentro: sin re-sellarla, la fórmula nueva la dejaría
        desfasada. El re-sellado es para las 32, no para las 31."""
        cambiados = resellar_decisiones.resellar(_leer(estado))
        assert len(cambiados) == 32
        assert "FM-019" in cambiados


class TestCriterio8Idempotencia:
    def test_la_segunda_corrida_no_cambia_nada(self, estado):
        resellar_decisiones.procesar(estado)
        primera = estado.read_bytes()
        assert resellar_decisiones.resellar(_leer(estado)) == []
        assert resellar_decisiones.procesar(estado) == 0
        assert estado.read_bytes() == primera


class TestCriterio6LosBloqueadoresFantasma:
    def test_de_121_a_59_sin_llevarse_ninguno_real_por_delante(self, estado):
        antes = [línea for línea in BLOQUEADORES_ANTES.read_text("utf-8").splitlines() if línea]
        assert len(antes) == 121
        fantasma = [b for b in antes if "La valoración del modo" in b and "desactualizada" in b]
        obsoletas = [b for b in antes if "La decisión del modo" in b and "desactualizada" in b]
        assert len(fantasma) == 31 and len(obsoletas) == 31

        resellar_decisiones.procesar(estado)
        despues = export_blockers(_sesion(estado))

        # Los 31 de valoración eran fantasmas: los scores estaban frescos y el
        # reporte los inventaba devolviendo la unión. Los 31 de decisión eran
        # reales bajo la fórmula vieja y el re-sellado los cierra.
        assert sorted(despues) == sorted(set(antes) - set(fantasma) - set(obsoletas))
        assert len(despues) == 59
        assert not [b for b in despues if "desactualizada" in b]

    def test_sin_resellar_no_queda_ninguna_desfasada(self, estado):
        """Sin tocar la base: la aceptación de sellos heredados reconoce los 32.

        Antes de existir esa aceptación este test afirmaba 32 desfasadas y 91
        bloqueadores — o sea, una ventana en la que desplegar dejaba el estado
        vivo PEOR que antes (32 en vez de 31) hasta correr la migración. Los
        controles son append-only, así que la lista de cualquier instante pasado
        es un prefijo de la actual y los sellos viejos se reconstruyen: 32 de 32.
        El estado sin migrar da ya los mismos 59 que el migrado.
        """
        sesion = _sesion(estado)
        assert sesion.stale_scores() == []
        assert sesion.stale_decisions() == []
        bloqueadores = export_blockers(sesion)
        assert not [b for b in bloqueadores if "La valoración del modo" in b]
        assert not [b for b in bloqueadores if "desactualizada" in b]
        assert len(bloqueadores) == 59


class TestElGuionVerificaLoQueAplico:
    """Un script de transformación que no comprueba lo que aplicó miente sobre su
    resultado (la cabecera de `scripts/mutar.py`). Estas son esas comprobaciones,
    probadas contra un resultado adulterado a mano."""

    def test_una_politica_cambiada_se_denuncia(self, estado):
        previo = resellar_decisiones.volcado(_leer(estado))
        adulterado = _leer(estado)
        adulterado["decisions"]["FM-019"]["policy"] = "OHF"
        fallos = resellar_decisiones._comparar(previo, adulterado)
        assert any("cambió 'policy'" in f for f in fallos)

    def test_una_firma_perdida_se_denuncia(self, estado):
        previo = resellar_decisiones.volcado(_leer(estado))
        adulterado = _leer(estado)
        firmado = next(
            fmid for fmid, d in adulterado["decisions"].items() if d["hitl_confirmed_by"]
        )
        adulterado["decisions"][firmado]["hitl_confirmed_by"] = None
        fallos = resellar_decisiones._comparar(previo, adulterado)
        assert any("hitl_confirmed_by" in f for f in fallos)

    def test_una_decision_que_sigue_obsoleta_se_denuncia(self, estado):
        previo = resellar_decisiones.volcado(_leer(estado))
        fallos = resellar_decisiones._comparar(previo, _leer(estado))  # sin aplicar nada
        # ESTRICTO, no `stale_decisions()`: esa acepta los sellos heredados para
        # que desplegar no degrade el estado vivo, y daría por bueno un fichero
        # en el que el guion no aplicó nada. Normalizar es justo su trabajo.
        assert any("siguen sin el sello canónico 32" in f for f in fallos)


class TestNoCorrompeUnEstadoReal:
    """Lo que encontró la validación de producción: el guión tenía una guarda
    para las decisiones huérfanas que su propia verificación anulaba, y un
    volcado que prometía una restauración que no podía cumplir."""

    def test_una_decision_huerfana_no_revienta_ni_deja_el_fichero_a_medias(self, estado):
        bruto = _leer(estado)
        bruto["decisions"]["FM-999"] = dict(
            bruto["decisions"]["FM-019"], failure_mode_id="FM-999"
        )
        estado.write_text(json.dumps(bruto, ensure_ascii=False), "utf-8")
        assert resellar_decisiones.procesar(estado) == 0
        sesion = _sesion(estado)
        assert sesion.decisiones_sin_sello_canonico() == []
        # La huérfana se salta: ni se re-sella ni se reporta como obsoleta.
        assert _leer(estado)["decisions"]["FM-999"]["input_hash"] == (
            bruto["decisions"]["FM-999"]["input_hash"]
        )

    def test_el_volcado_es_una_copia_entera_y_restaurable(self, estado):
        original = estado.read_bytes()
        resellar_decisiones.procesar(estado)
        copia = estado.parent / "uat.antes.json"
        assert copia.read_bytes() == original

    def test_la_segunda_corrida_no_pisa_el_volcado(self, estado):
        original = estado.read_bytes()
        resellar_decisiones.procesar(estado)
        resellar_decisiones.procesar(estado)
        assert (estado.parent / "uat.antes.json").read_bytes() == original

    def test_un_json_roto_no_escribe_nada(self, tmp_path):
        ruta = tmp_path / "roto.json"
        ruta.write_text('{"decisions": {', "utf-8")
        assert resellar_decisiones.procesar(ruta) == 2
        assert ruta.read_text("utf-8") == '{"decisions": {'
        assert not (tmp_path / "roto.antes.json").exists()

    def test_un_json_que_no_es_una_sesion_no_escribe_nada(self, tmp_path):
        ruta = tmp_path / "otro.json"
        ruta.write_text('{"decisions": {"FM-001": 3}}', "utf-8")
        assert resellar_decisiones.procesar(ruta) == 2
        assert ruta.read_text("utf-8") == '{"decisions": {"FM-001": 3}}'


class TestLaLineaDeComandos:
    def test_acepta_el_estado_envuelto_de_agno(self, tmp_path):
        ruta = tmp_path / "session_state.json"
        ruta.write_text(
            json.dumps({"rcm": _leer(FIXTURE), "otra_clave": 1}, ensure_ascii=False), "utf-8"
        )
        assert resellar_decisiones.procesar(ruta) == 0
        bruto = _leer(ruta)
        assert bruto["otra_clave"] == 1
        assert RCMSession.model_validate(bruto["rcm"]).stale_decisions() == []

    def test_como_proceso_devuelve_cero_y_deja_el_volcado(self, estado):
        proc = subprocess.run(
            [sys.executable, str(GUION), str(estado)],
            capture_output=True, text=True, cwd=RAIZ,
        )
        assert proc.returncode == 0, proc.stderr
        assert (estado.parent / "uat.antes.json").is_file()
        assert "re-selladas 32 de 32" in proc.stdout

    def test_sin_argumentos_no_hace_nada_y_avisa(self):
        assert resellar_decisiones.main([str(GUION)]) == 2

    def test_un_fichero_que_no_existe_no_pasa_por_verde(self, tmp_path):
        assert resellar_decisiones.main([str(GUION), str(tmp_path / "no-esta.json")]) == 2


class TestReconoceElVolcadoDeProduccion:
    """La forma que baja un operador para migrar es la anidada de agno, y es la
    que el guion NO reconocía: procesaba el fichero, no tocaba nada, y lo
    celebraba con un ✔ y salida 0 — la verificación confirmaba su propio no-op.
    Es justo lo que la cabecera de `scripts/mutar.py` advierte."""

    def _envuelto(self, estado: Path, tmp_path: Path) -> Path:
        destino = tmp_path / "de_produccion.json"
        destino.write_text(
            json.dumps({"session_data": {"session_state": {"rcm": _leer(estado)}}}),
            "utf-8",
        )
        return destino

    def test_resella_las_32_y_conserva_la_envoltura(self, estado, tmp_path):
        antes = _leer(estado)["decisions"]
        envuelto = self._envuelto(estado, tmp_path)
        assert resellar_decisiones.procesar(envuelto) == 0
        bruto = _leer(envuelto)
        assert "session_data" in bruto, "la envoltura no puede perderse al escribir"
        dentro = bruto["session_data"]["session_state"]["rcm"]
        cambiados = [
            fmid for fmid, d in dentro["decisions"].items()
            if d["input_hash"] != antes[fmid]["input_hash"]
        ]
        assert len(cambiados) == 32
        assert RCMSession.model_validate(dentro).decisiones_sin_sello_canonico() == []

    def test_un_json_que_no_es_una_sesion_se_rechaza_sin_escribir(self, tmp_path):
        """`RCMSession.model_validate({})` acepta el diccionario vacío —todos los
        campos tienen valor por defecto—, así que validar no distingue «sesión
        sin decisiones» de «esto no es una sesión»."""
        ajeno = tmp_path / "cualquiera.json"
        ajeno.write_text('{"hola": 1}', "utf-8")
        antes = ajeno.read_bytes()
        assert resellar_decisiones.procesar(ajeno) == 2
        assert ajeno.read_bytes() == antes
        assert not (tmp_path / "cualquiera.antes.json").exists()


class TestLaToleranciaNoSeTragaUnCambioReal:
    """El único punto donde la aceptación de sellos heredados podría volverse
    permisiva de más sin que nadie se entere.

    Todos los tests de invariancia corren sobre una sesión SIN controles, así
    que el conjunto tolerante tiene un solo elemento y la aceptación nunca se
    ejercita en su modo «rechazar». Acá sí: sello heredado, lista de controles
    no vacía, y un insumo real cambiado.
    """

    @pytest.mark.parametrize(
        ("campo", "valor"),
        [
            ("pf_interval_hours", 12345.0),
            ("weibull_eta_hours", 54321.0),
            ("failure_pattern", "Mortalidad Infantil"),
        ],
    )
    def test_con_sello_heredado_y_controles_un_cambio_real_sigue_obsoleta(
        self, estado, campo, valor
    ):
        sesion = _sesion(estado)
        fmid = next(f for f in sesion.decisions if sesion.controls.get(f))
        assert sesion.stale_decisions() == [], "de partida, el heredado se acepta"
        fm = sesion.failure_modes[fmid]
        sesion.failure_modes[fmid] = fm.model_copy(update={campo: valor})
        assert fmid in sesion.stale_decisions(), f"'{campo}' se lo tragó la tolerancia"
