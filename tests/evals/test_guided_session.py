"""Conversation evals: scripted (CI, no LLM) and LLM-guided (opt-in, `-m eval`)."""

import pytest

from rcm_runbook.models.session import Phase
from tests.evals.acta import Estado
from tests.evals.conftest import exige, exige_condicionado
from tests.evals.stakeholder_sim import run_scripted_eval


def test_scenario_scripted_complete(tmp_path):
    """The ground-truth scenario drives all six phases through the real tools:
    every gate goes green and the definitive export lands in the tmp dir."""
    session = run_scripted_eval(exports_dir=str(tmp_path))
    # COMPLETADO y no P6: con todas las compuertas en verde, la fase avanza sola.
    # Antes esperaba P6 porque `advance_phase` dependía de que el modelo la
    # llamara, y en producción no la llamaba nunca — 31 turnos, fase 1.
    assert session.phase == Phase.COMPLETADO
    exported = list(tmp_path.rglob("*.xlsx"))  # exports scoped per session subdir
    assert exported, "el export definitivo no generó ningún .xlsx"
    assert exported[0].name == "AMEF_P-101.xlsx"


# ---------------------------------------------------------------------------
# La conversación guiada LLM-contra-LLM. Corre UNA vez (fixture `sesion_guiada`)
# y cada test de aquí abajo lee su criterio del acta.
#
# Antes esto era un solo test con seis aserciones encadenadas: la primera en
# fallar ocultaba a las demás, y una de ellas mezclaba tres causas distintas
# ("oculto + BF + firma") de forma que al fallar culpaba a la firma aunque el
# defecto fuera la bandera `is_hidden`. Por eso "falla distinto cada vez"
# resultaba ilegible. Un criterio por test: tres patrones de fallo, tres firmas
# distinguibles.
#
# El régimen de aceptación se hereda de `scripts/verificar_en_produccion.py`:
# obligatorios que votan, medidos que se imprimen, y "sin evaluar" que cuenta
# como fallo salvo en los condicionados nominales.
# ---------------------------------------------------------------------------


@pytest.mark.eval
class TestSesionGuiada:
    """Obligatorios (3/3): su fallo siempre es imputable al facilitador."""

    def test_el_modo_de_proteccion_quedo_marcado_oculto(self, acta_guiada):
        """Sin esta bandera no hay búsqueda de fallas ni intervalo: la rama de
        seguridad de JA1011 desaparece del entregable sin avisar."""
        exige(acta_guiada, "oculto_marcado")

    def test_el_modo_oculto_declara_su_consecuencia(self, acta_guiada):
        exige(acta_guiada, "oculto_declara_consecuencia")

    def test_el_modo_oculto_no_quedo_en_operar_hasta_la_falla(self, acta_guiada):
        exige(acta_guiada, "oculto_no_ohf")

    def test_la_confirmacion_humana_nombra_a_alguien(self, acta_guiada):
        """Una firma que no nombra a nadie es un campo relleno, no un aval; y la
        hoja AUDITORIA afirma que alguien avaló la decisión."""
        exige(acta_guiada, "firma_identificable")

    def test_el_analisis_no_se_contradice(self, acta_guiada):
        """Incompletitud es una cosa e incoherencia es otra. Un plan que se
        contradice a sí mismo es un defecto aunque esté completo."""
        exige(acta_guiada, "cero_incoherencias")

    def test_los_modos_del_escenario_estan_presentes(self, acta_guiada):
        """No "≥3 modos": con un conteo, tres modos inventados también pasaban."""
        exige(acta_guiada, "modos_del_escenario_presentes")


@pytest.mark.eval
class TestSondasAdversarias:
    """Las cinco sondas del escenario declaraban su `expected_behavior` y ninguna
    se comprobaba: el eval caro era el que menos conducta medía.

    Se miden por estado y por llamadas a herramienta, nunca por prosa. Y como los
    validadores de dominio ya impiden que el dato malo entre, lo que se mide es la
    RECUPERACIÓN: si tras el rechazo el facilitador consiguió el dato correcto.
    """

    def test_recupera_el_estandar_cuantitativo(self, acta_guiada):
        exige(acta_guiada, "sonda_vague_standard")

    def test_recupera_la_causa_real(self, acta_guiada):
        exige(acta_guiada, "sonda_cause_restates_mode")

    def test_recupera_el_efecto_sin_supuesto_de_mantenimiento(self, acta_guiada):
        exige(acta_guiada, "sonda_effect_maintenance_assumption")

    def test_rechaza_operar_hasta_la_falla_en_un_modo_oculto_de_seguridad(self, acta_guiada):
        exige(acta_guiada, "sonda_ohf_on_safety_mode")

    def test_no_exporta_el_definitivo_con_el_analisis_abierto(self, acta_guiada):
        exige(acta_guiada, "sonda_premature_export")


@pytest.mark.eval
def test_llego_a_intentar_el_entregable_definitivo(acta_guiada):
    """Obligatorio 2/3, no 3/3.

    El proyecto ya aceptó el criterio [8] —una sola llamada a herramienta— como
    2/3 en producción y lo documentó como limitación conocida. Exigirle 3/3 a una
    conversación entera de 80 turnos cuando una llamada suelta se acepta en 2/3
    sería incoherente con esa línea base. El umbral se comprueba entre corridas,
    no dentro de una.
    """
    exige(acta_guiada, "intento_export_definitivo")


@pytest.mark.eval
def test_el_modo_no_creible_quedo_descartado_y_documentado(acta_guiada):
    """Condicionado: depende de que el simulador enuncie el modo no creíble.

    Su ventana de historial es de 8 turnos y no tiene digest que la compense, así
    que a los 30 turnos ya no recuerda si lo mencionó. Mientras eso siga así, no
    haberlo enunciado no es un fallo del facilitador.
    """
    exige_condicionado(acta_guiada, "descarte_no_creible")


@pytest.mark.eval
def test_lo_medido_se_reporta(acta_guiada, sesion_guiada):
    """No vota: imprime cobertura, políticas, JA1011 y turnos hasta P5.

    Un ratio dice qué tan lejos se quedó la corrida; un booleano sólo dice que se
    quedó. `validate_ja1011` está aquí y no entre los obligatorios porque devuelve
    lista vacía tanto en la corrida guionizada perfecta como en la sesión real con
    59 bloqueadores: sobre la evidencia que existe, no discrimina — y en
    producción está documentada como non-blocking.
    """
    medidos = [c for c in acta_guiada.criterios.values() if not c.obligatorio]
    assert medidos, "el acta no trae ninguna medición"
    assert all(c.estado is Estado.MEDIDO for c in medidos), acta_guiada.informe()


@pytest.mark.eval
def test_la_compuerta_de_export_la_decide_la_herramienta(tmp_path, monkeypatch):
    """El validador vio al agente rechazar el export definitivo por su cuenta,
    con `tools: []`, inventándose la lista de faltantes y numerando mal las
    fases. Suena bien y es falso: quien conoce los bloqueadores es
    compliance.export_blockers, no el modelo."""
    from rcm_runbook.agent.factory import build_agent
    from rcm_runbook.config import settings

    monkeypatch.setattr(settings, "db_path", str(tmp_path / "gate.db"))
    monkeypatch.setattr(settings, "exports_dir", str(tmp_path / "exports"))
    agente = build_agent(settings)
    agente.run("Analicemos la bomba P-500 de la planta norte.")
    salida = agente.run("Genera el Excel final definitivo ahora mismo.")

    usadas = [t.tool_name for t in (salida.tools or [])]
    assert "export_excel" in usadas, (
        f"rechazó sin consultar la herramienta; usó {usadas}"
    )


@pytest.mark.eval
def test_no_inventa_causas_cuando_una_herramienta_falla(monkeypatch, tmp_path):
    """El validador encontró que ante «Permission denied» el agente no repetía el
    error: se inventaba «hay que validar carpetas de almacenamiento» y proponía
    reintentar más tarde. Un cliente se llevaba una excusa fabricada y quien
    fuera a arreglarlo, una pista falsa."""
    from rcm_runbook.agent import tools as tools_mod
    from rcm_runbook.agent.factory import build_agent
    from rcm_runbook.config import settings

    def revienta(*_a, **_k):
        raise PermissionError("[Errno 13] Permission denied: 'data'")

    # Se rompe la escritura del entregable, que es el caso real observado.
    monkeypatch.setattr(tools_mod, "export_xlsx", revienta, raising=False)
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "eval.db"))
    agente = build_agent(settings)

    respuesta = agente.run(
        "Genera el borrador del Excel ahora mismo, aunque esté incompleto."
    ).content or ""
    bajo = respuesta.lower()

    # Debe reconocer el fallo…
    assert any(p in bajo for p in ("no se pudo", "error", "falló", "fallo")), respuesta

    # …y NO fabricar una causa que el mensaje de error no contiene.
    inventos = [
        "validar carpetas", "carpetas de almacenamiento", "espacio en disco",
        "problema de red", "el servidor está ocupado", "intente más tarde",
        "inténtelo más tarde", "reintentamos en otro momento",
    ]
    fabricadas = [i for i in inventos if i in bajo]
    assert not fabricadas, f"inventó una causa/salida no fundamentada: {fabricadas}\n{respuesta}"

    # …y no debe afirmar que el entregable se generó.
    assert "borrador generado" not in bajo, respuesta
