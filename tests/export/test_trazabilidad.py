"""Trazabilidad y clasificación del entregable.

Spec: `specs/trazabilidad-y-clasificacion-en-el-excel.md`.

Estos tests corren sobre `tests/fixtures/uat_sesion_real.json`, el estado
congelado de la sesión de UAT (63 modos, 60 creíbles, 32 decisiones), y no
sobre el fixture sintético de dos modos. La razón es la de la spec: `full_session()`
tiene todo completo por construcción, así que no puede fallar por ninguno de los
defectos que esta feature arregla — pasaría en verde sobre un caso que nunca
falla.
"""

import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

from rcm_runbook.engine.compliance import export_blockers
from rcm_runbook.engine.decision_logic import derive_route
from rcm_runbook.export.excel import (
    AMEF_HEADER_ROW,
    DRAFT_STAMP,
    ID_HEADER,
    PLAN_HEADER_ROW,
    export_xlsx,
)
from rcm_runbook.export.rows import (
    SIN_DECISION,
    amef_rows_with_ids,
    plan_rows_with_ids,
)
from rcm_runbook.models.catalogs import MaintenancePolicy
from rcm_runbook.models.session import RCMSession

FIXTURE_UAT = Path(__file__).parents[1] / "fixtures" / "uat_sesion_real.json"


@pytest.fixture(scope="module")
def sesion() -> RCMSession:
    return RCMSession.model_validate(json.loads(FIXTURE_UAT.read_text("utf-8")))


@pytest.fixture(scope="module")
def libro(sesion, tmp_path_factory):
    ruta = export_xlsx(sesion, tmp_path_factory.mktemp("uat"), draft=True)
    return load_workbook(ruta)


class TestCriterio1Trazabilidad:
    """Todo modo exportado se localiza por su código sin leer descripciones."""

    def test_amef_lleva_el_id_en_la_columna_a(self, sesion, libro):
        ws = libro["AMEF"]
        assert ws.cell(row=AMEF_HEADER_ROW, column=1).value == ID_HEADER
        esperados = [fmid for fmid, _ in amef_rows_with_ids(sesion)]
        obtenidos = [
            ws.cell(row=r, column=1).value
            for r in range(AMEF_HEADER_ROW + 1, AMEF_HEADER_ROW + 1 + len(esperados))
        ]
        assert obtenidos == esperados

    def test_plan_lleva_el_id_en_la_columna_a(self, sesion, libro):
        ws = libro["PLAN DE MANTENIMIENTO"]
        assert ws.cell(row=PLAN_HEADER_ROW, column=1).value == ID_HEADER
        esperados = [fmid for fmid, _ in plan_rows_with_ids(sesion)]
        obtenidos = [
            ws.cell(row=r, column=1).value
            for r in range(PLAN_HEADER_ROW + 1, PLAN_HEADER_ROW + 1 + len(esperados))
        ]
        assert obtenidos == esperados

    def test_la_falla_funcional_empieza_por_su_codigo(self, sesion):
        for _, fila in amef_rows_with_ids(sesion):
            assert fila.falla_funcional.startswith("FF-"), fila.falla_funcional

    def test_el_bloque_tpef_no_invade_la_columna_a(self, libro):
        """El bloque TPEF vive encima de la cabecera del PLAN y deja A vacía."""
        ws = libro["PLAN DE MANTENIMIENTO"]
        for r in range(1, PLAN_HEADER_ROW):
            assert ws.cell(row=r, column=1).value in (None, "")


class TestCriterio3SinCeldasMudas:
    def test_ninguna_fila_amef_queda_sin_clasificar(self, sesion):
        mudas = [
            fmid for fmid, fila in amef_rows_with_ids(sesion)
            if not fila.evidente and not fila.oculta
        ]
        assert mudas == [], f"{len(mudas)} filas mudas: {mudas[:5]}"

    def test_ninguna_fila_plan_queda_sin_clasificar(self, sesion):
        mudas = [
            fmid for fmid, fila in plan_rows_with_ids(sesion)
            if not fila.evidente and not fila.oculta
        ]
        assert mudas == []

    def test_el_centinela_va_en_la_columna_de_la_visibilidad(self, sesion):
        """Oculta -> AEFG, evidente -> ABCD. Nunca en ambas: la fila sigue
        comunicando lo que el análisis sí determinó."""
        for fmid, fila in amef_rows_with_ids(sesion):
            if SIN_DECISION not in (fila.evidente, fila.oculta):
                continue
            efecto = sesion.effects.get(fmid)
            assert efecto is not None
            if efecto.is_hidden:
                assert fila.oculta == SIN_DECISION and fila.evidente == ""
            else:
                assert fila.evidente == SIN_DECISION and fila.oculta == ""

    def test_toda_letra_impresa_es_reproducible(self, sesion):
        """La ruta se recalcula con `derive_route`: una letra que no se puede
        reproducir no se imprime. Se formula así y no como «proviene de un
        DecisionResult» porque la procedencia no se puede demostrar leyendo el
        libro, y `DecisionResult` no valida coherencia."""
        letras = set("ABCDEFG")
        for fmid, fila in amef_rows_with_ids(sesion):
            impresa = {fila.evidente, fila.oculta} & letras
            if not impresa:
                continue
            decision = sesion.decisions[fmid]
            efecto = sesion.effects[fmid]
            calc_e, calc_o = derive_route(efecto, MaintenancePolicy(decision.policy))
            assert (fila.evidente, fila.oculta) == (calc_e or "", calc_o or "")

    def test_una_ruta_incoherente_no_se_imprime(self, sesion):
        """Un estado histórico con una ruta imposible no llega al papel."""
        corrupta = sesion.model_copy(deep=True)
        fmid = next(
            f for f, d in corrupta.decisions.items()
            if d.evident_route and corrupta.effects.get(f)
        )
        # B sobre un efecto que la lógica resolvería de otro modo
        corrupta.decisions[fmid] = corrupta.decisions[fmid].model_copy(
            update={"evident_route": "D" if corrupta.decisions[fmid].evident_route != "D" else "C"}
        )
        fila = dict(amef_rows_with_ids(corrupta))[fmid]
        assert fila.evidente not in ("D", "C") or fila.oculta != ""
        assert "PENDIENTE" in (fila.evidente or fila.oculta)


class TestCriterio4SinDesaparicionesSilenciosas:
    def test_todo_modo_creible_sin_decision_aparece_en_el_plan(self, sesion):
        creibles = {f for f, fm in sesion.failure_modes.items() if fm.credible}
        en_plan = {fmid for fmid, _ in plan_rows_with_ids(sesion)}
        assert creibles - en_plan == set()

    def test_los_no_creibles_siguen_fuera(self, sesion):
        no_creibles = {f for f, fm in sesion.failure_modes.items() if not fm.credible}
        assert no_creibles
        en_plan = {fmid for fmid, _ in plan_rows_with_ids(sesion)}
        en_amef = {fmid for fmid, _ in amef_rows_with_ids(sesion)}
        assert no_creibles & (en_plan | en_amef) == set()


class TestCriterio5BorradorHonesto:
    def test_el_sello_esta_dentro_del_libro(self, libro):
        for hoja in ("AMEF", "PLAN DE MANTENIMIENTO"):
            fila2 = [c.value for c in libro[hoja][2]]
            assert DRAFT_STAMP in fila2, hoja

    def test_los_bloqueadores_viajan_con_el_entregable(self, sesion, libro):
        """Cada bloqueador que menciona un modo lleva su FM-id en celda propia,
        para que se pueda afirmar sin analizar prosa."""
        ws = libro["AUDITORIA RCM"]
        ids_en_hoja = {
            str(c.value) for c in ws["A"] if c.value and str(c.value).startswith("FM-")
        }
        import re

        ids_con_defecto = {
            m.group(1)
            for b in export_blockers(sesion)
            if (m := re.search(r"\b(FM-\d+)\b", b))
        }
        assert ids_con_defecto
        assert ids_con_defecto <= ids_en_hoja

    def test_el_definitivo_no_lleva_sello(self, sesion, tmp_path):
        ruta = export_xlsx(sesion, tmp_path, draft=False)
        wb = load_workbook(ruta)
        assert DRAFT_STAMP not in [c.value for c in wb["AMEF"][2]]
