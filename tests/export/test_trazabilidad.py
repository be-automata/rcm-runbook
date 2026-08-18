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
import re
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
    DECISION_SIN_RUTA,
    RUTA_INCONSISTENTE,
    SIN_DECISION,
    amef_rows_with_ids,
    plan_rows_with_ids,
    rutas_inconsistentes,
)
from rcm_runbook.models.catalogs import MaintenancePolicy
from rcm_runbook.models.session import RCMSession

FIXTURE_UAT = Path(__file__).parents[1] / "fixtures" / "uat_sesion_real.json"


@pytest.fixture(scope="module")
def sesion() -> RCMSession:
    return RCMSession.model_validate(json.loads(FIXTURE_UAT.read_text("utf-8")))


@pytest.fixture(scope="module")
def libro(tmp_path_factory):
    # Recarga propia y no la `sesion` compartida: esa es mutable y de ámbito
    # módulo, así que el libro dependería de qué test la tocó primero. Hoy
    # ninguno la muta en sitio, pero el aislamiento sería accidental.
    propia = RCMSession.model_validate(json.loads(FIXTURE_UAT.read_text("utf-8")))
    ruta = export_xlsx(propia, tmp_path_factory.mktemp("uat"), draft=True)
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

    def test_el_aviso_del_bloque_tpef_no_pisa_una_fila_poblada(self, libro):
        """El aviso «ver AUDITORIA» va en su propia fila. Antes se escribía
        encima de la última fila ya poblada: pisaba su FM- y dejaba las horas,
        los años y la fuente sin el modo al que pertenecen."""
        ws = libro["PLAN DE MANTENIMIENTO"]
        avisos = [
            r for r in range(1, PLAN_HEADER_ROW)
            if "ver hoja AUDITORIA" in str(ws.cell(row=r, column=14).value or "")
        ]
        assert avisos, "el fixture ya no desborda el bloque TPEF"
        for r in avisos:
            resto = [ws.cell(row=r, column=c).value for c in (15, 16, 17)]
            assert resto == [None, None, None], f"fila {r} dejó datos huérfanos: {resto}"

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
        vistos = 0
        for fmid, fila in amef_rows_with_ids(sesion):
            if SIN_DECISION not in (fila.evidente, fila.oculta):
                continue
            vistos += 1
            efecto = sesion.effects.get(fmid)
            assert efecto is not None
            if efecto.is_hidden:
                assert fila.oculta == SIN_DECISION and fila.evidente == ""
            else:
                assert fila.evidente == SIN_DECISION and fila.oculta == ""
        # Sin esta precondición el test pasa en vacío si el fixture cambiara y
        # todos los modos llegaran a tener decisión.
        assert vistos > 0, "el fixture ya no ejercita el centinela"

    def test_toda_letra_impresa_es_reproducible(self, sesion):
        """La ruta se recalcula con `derive_route`: una letra que no se puede
        reproducir no se imprime. Se formula así y no como «proviene de un
        DecisionResult» porque la procedencia no se puede demostrar leyendo el
        libro, y `DecisionResult` no valida coherencia."""
        letras = set("ABCDEFG")
        vistos = 0
        for fmid, fila in amef_rows_with_ids(sesion):
            impresa = {fila.evidente, fila.oculta} & letras
            if not impresa:
                continue
            vistos += 1
            decision = sesion.decisions[fmid]
            efecto = sesion.effects[fmid]
            calc_e, calc_o = derive_route(efecto, MaintenancePolicy(decision.policy))
            assert (fila.evidente, fila.oculta) == (calc_e or "", calc_o or "")
        assert vistos > 0, "el fixture ya no tiene ninguna letra que contrastar"

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
        assert RUTA_INCONSISTENTE in (fila.evidente, fila.oculta)
        assert fmid in {d[0] for d in rutas_inconsistentes(corrupta)}

    def test_el_renglon_de_auditoria_distingue_evidente_de_oculta(self, sesion):
        """Una ruta evidente A y una oculta A son distintas y se ven iguales si
        se aplana la tupla: el renglón decía «guardada: A — contraste: A», o sea
        afirmaba una discrepancia mostrando dos veces el mismo valor."""
        girada = sesion.model_copy(deep=True)
        fmid = next(
            f for f, d in girada.decisions.items()
            if d.evident_route == "A" and girada.effects.get(f)
        )
        girada.effects[fmid] = girada.effects[fmid].model_copy(
            update={"is_hidden": True, "evident_route": None}
        )
        (_, guardada, contraste), = [
            d for d in rutas_inconsistentes(girada) if d[0] == fmid
        ]
        assert guardada != contraste
        assert guardada == "evidente:A" and contraste == "oculta:A"

    def test_decision_sin_ninguna_ruta_no_dice_sin_decision(self, sesion):
        """`DecisionResult` deja ambas rutas opcionales, así que un estado
        histórico puede traer decisión y ninguna letra. Esa fila muestra su
        política, su tarea y su ejecutor: etiquetarla «sin decisión RCM» la
        contradice con sus propias columnas. Y tiene que dejar rastro en
        AUDITORIA, que es lo que antes se perdía por un `continue`."""
        muda = sesion.model_copy(deep=True)
        fmid = next(f for f, d in muda.decisions.items() if d.evident_route or d.hidden_route)
        muda.decisions[fmid] = muda.decisions[fmid].model_copy(
            update={"evident_route": None, "hidden_route": None}
        )
        fila = dict(amef_rows_with_ids(muda))[fmid]
        assert DECISION_SIN_RUTA in (fila.evidente, fila.oculta)
        assert SIN_DECISION not in (fila.evidente, fila.oculta)
        assert fila.estrategia, "la fila sí tiene política: por eso la etiqueta importa"
        assert fmid in {d[0] for d in rutas_inconsistentes(muda)}

    def test_ruta_sin_efecto_no_se_imprime(self, sesion):
        """Sin efecto no hay con qué recalcular: la letra no es reproducible."""
        sin_efecto = sesion.model_copy(deep=True)
        fmid = next(
            f for f, d in sin_efecto.decisions.items()
            if (d.evident_route or d.hidden_route) and sin_efecto.failure_modes[f].credible
        )
        del sin_efecto.effects[fmid]
        fila = dict(amef_rows_with_ids(sin_efecto))[fmid]
        assert RUTA_INCONSISTENTE in (fila.evidente, fila.oculta)
        assert fmid in {d[0] for d in rutas_inconsistentes(sin_efecto)}

    def test_sin_efecto_la_visibilidad_sale_de_la_decision(self, sesion):
        """Sin `Effect` la visibilidad no se pierde: `consequence_class` es
        obligatorio. Antes el centinela caía siempre en la columna de falla
        evidente, así que el libro clasificaba como evidente una falla que la
        propia decisión guardada declara oculta."""
        sin_efecto = sesion.model_copy(deep=True)
        fmid = next(
            f for f, d in sin_efecto.decisions.items()
            if d.hidden_route and sin_efecto.failure_modes[f].credible
        )
        del sin_efecto.effects[fmid]
        fila = dict(amef_rows_with_ids(sin_efecto))[fmid]
        assert fila.oculta == RUTA_INCONSISTENTE, "el centinela cayó en la columna equivocada"
        assert fila.evidente == ""


class TestCriterio4SinDesaparicionesSilenciosas:
    def test_todo_modo_creible_sin_decision_aparece_en_el_plan(self, sesion):
        creibles = {f for f, fm in sesion.failure_modes.items() if fm.credible}
        sin_decision = {f for f in creibles if f not in sesion.decisions}
        assert sin_decision, "el fixture ya no tiene modos sin decisión que proteger"
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
