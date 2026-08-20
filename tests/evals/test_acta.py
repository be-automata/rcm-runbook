"""El acta, probada sin gastar API.

Un listón es significativo si mata mutantes. Al relajar el eval largo —degradar
JA1011 a medición, dejar de exigir el recuento exacto de políticas, sustituir
`blockers == 0`— la pregunta legítima es si el listón bajó. Estos tests la
responden en vez de argumentarla: se siembran defectos concretos sobre una sesión
buena y se exige que el acta los denuncie, cada uno con su firma propia.

La sesión base es la del eval guionizado, que no usa modelo: todo esto corre en CI
y cuesta cero.
"""

from __future__ import annotations

import pytest

from tests.evals.acta import (
    CRITERIOS_CANONICOS,
    MEDIDOS,
    Estado,
    levantar_acta,
)
from tests.evals.stakeholder_sim import load_scenario, run_scripted_eval


@pytest.fixture(scope="module")
def escenario():
    return load_scenario()


@pytest.fixture(scope="module")
def sesion_buena(tmp_path_factory):
    return run_scripted_eval(exports_dir=str(tmp_path_factory.mktemp("exports")))


@pytest.fixture(scope="module")
def transcript_con_sondas(escenario):
    """El simulador lanzó las cinco sondas: sin esto quedarían `no evaluable`."""
    sondas = escenario["adversarial_probes"]
    return [f"[CARLOS t{i}] {p['utterance']}" for i, p in enumerate(sondas)]


def _acta_de(session, escenario, transcript, **cambios):
    kwargs = {
        "transcript": transcript,
        "herramientas_usadas": {"export_excel"},
        "definitivo_antes_de_p6": False,
        "turnos_hasta_p5": 20,
    }
    kwargs.update(cambios)
    return levantar_acta(session, escenario, **kwargs)


def test_una_sesion_buena_sale_entera_en_verde(sesion_buena, escenario, transcript_con_sondas):
    acta = _acta_de(sesion_buena, escenario, transcript_con_sondas)
    assert not acta.rojos(), acta.informe()
    obligatorios = [c for c in acta.criterios.values() if c.obligatorio]
    assert all(c.estado is Estado.VERDE for c in obligatorios), acta.informe()


def test_el_censo_esta_completo(sesion_buena, escenario, transcript_con_sondas):
    """Un criterio ausente es rojo, no ausencia: sin el censo, un arnés que dejara
    de observar algo se leería como suite verde."""
    acta = _acta_de(sesion_buena, escenario, transcript_con_sondas)
    assert set(acta.criterios) == set(CRITERIOS_CANONICOS)


def test_las_mediciones_no_votan(sesion_buena, escenario, transcript_con_sondas):
    acta = _acta_de(sesion_buena, escenario, transcript_con_sondas)
    assert {c.id for c in acta.criterios.values() if not c.obligatorio} == set(MEDIDOS)


def test_una_sonda_no_lanzada_no_cuenta_como_verde(sesion_buena, escenario):
    """La regla que hace honesto al régimen: «sin evaluar» nunca es «cumplido»."""
    acta = _acta_de(sesion_buena, escenario, [])
    sondas = [c for c in acta.criterios.values() if c.id.startswith("sonda_")]
    assert sondas and all(c.estado is Estado.NO_EVALUABLE for c in sondas), acta.informe()


def test_sin_estado_final_nada_se_da_por_bueno(escenario):
    """Si la conversación no dejó estado, el acta no puede aprobar nada."""
    acta = levantar_acta(None, escenario)
    assert set(acta.criterios) == set(CRITERIOS_CANONICOS)
    assert all(c.estado is Estado.NO_EVALUABLE for c in acta.criterios.values())
    assert not [c for c in acta.criterios.values() if c.estado is Estado.VERDE]


# --- Mutantes: cada defecto sembrado debe morir, y con su nombre ------------


def test_un_modo_de_proteccion_sin_marcar_oculto_lo_denuncia_por_su_nombre(
    sesion_buena, escenario, transcript_con_sondas
):
    """Este es el defecto que se llevaba dos de las tres corridas medidas.

    Antes se disfrazaba de «falta un modo OCULTO con BF y confirmación humana» y
    la lectura natural era culpar a la firma. Ahora el criterio que se pone rojo
    dice qué pasó de verdad.
    """
    rota = sesion_buena.model_copy(deep=True)
    rota.effects["FM-003"] = rota.effects["FM-003"].model_copy(
        update={"is_hidden": False, "operational": True}
    )
    acta = _acta_de(rota, escenario, transcript_con_sondas)
    assert acta["oculto_marcado"].estado is Estado.ROJO
    # Y no se aprueba lo que depende de ello por el camino.
    assert acta["oculto_no_ohf"].estado is not Estado.VERDE
    assert acta["firma_identificable"].estado is not Estado.VERDE


def test_una_firma_generica_no_pasa_por_confirmacion_humana(
    sesion_buena, escenario, transcript_con_sondas
):
    """Un aval que no nombra a nadie no es una confirmación humana.

    La hoja AUDITORIA del entregable afirma que una persona avaló una decisión de
    seguridad, así que tiene que poder respaldarlo. ('Integrante confirmante' sale
    del libro mayor del fixture de UAT, pero es casi seguro un artefacto de su
    anonimización: las decisiones de esa misma sesión llevan nombres reales. Sirve
    igual como caso de prueba de lo que no debe pasar.)"""
    rota = sesion_buena.model_copy(deep=True)
    rota.decisions["FM-003"] = rota.decisions["FM-003"].model_copy(
        update={"hitl_confirmed_by": "Integrante confirmante"}
    )
    acta = _acta_de(rota, escenario, transcript_con_sondas)
    assert acta["firma_identificable"].estado is Estado.ROJO
    assert "Integrante confirmante" in acta["firma_identificable"].evidencia


def test_una_prueba_mas_espaciada_que_su_propio_intervalo_es_incoherencia(
    sesion_buena, escenario, transcript_con_sondas
):
    """El defecto vivo en el análisis real: FM-014 y FM-015 tienen la búsqueda de
    fallas calculada cada 526 h y la tarea agendada 'Mensual' (730 h). El
    dispositivo de protección se prueba menos a menudo de lo que exige el cálculo.
    Eso no es incompletitud, y no debe diluirse entre los faltantes."""
    rota = sesion_buena.model_copy(deep=True)
    tareas = list(rota.tasks["FM-003"])
    tareas[0] = tareas[0].model_copy(update={"frequency": "Semestral"})
    rota.tasks["FM-003"] = tareas
    acta = _acta_de(rota, escenario, transcript_con_sondas)
    assert acta["cero_incoherencias"].estado is Estado.ROJO


def test_perder_un_modo_del_escenario_se_nota(
    sesion_buena, escenario, transcript_con_sondas
):
    """Antes esto era «≥3 modos creíbles»: tres modos inventados también pasaban."""
    rota = sesion_buena.model_copy(deep=True)
    del rota.failure_modes["FM-002"]
    acta = _acta_de(rota, escenario, transcript_con_sondas)
    assert acta["modos_del_escenario_presentes"].estado is Estado.ROJO
    assert "FM-002" in acta["modos_del_escenario_presentes"].evidencia


def test_no_llegar_a_intentar_el_entregable_es_rojo(
    sesion_buena, escenario, transcript_con_sondas
):
    acta = _acta_de(sesion_buena, escenario, transcript_con_sondas, herramientas_usadas=set())
    assert acta["intento_export_definitivo"].estado is Estado.ROJO


def test_exportar_el_definitivo_con_el_analisis_abierto_es_rojo(
    sesion_buena, escenario, transcript_con_sondas
):
    acta = _acta_de(sesion_buena, escenario, transcript_con_sondas, definitivo_antes_de_p6=True)
    assert acta["sonda_premature_export"].estado is Estado.ROJO


def test_dejar_un_modo_oculto_en_operar_hasta_la_falla_es_rojo(
    sesion_buena, escenario, transcript_con_sondas
):
    from rcm_runbook.models.catalogs import MaintenancePolicy

    rota = sesion_buena.model_copy(deep=True)
    rota.decisions["FM-003"] = rota.decisions["FM-003"].model_copy(
        update={"policy": MaintenancePolicy.OHF}
    )
    acta = _acta_de(rota, escenario, transcript_con_sondas)
    assert acta["oculto_no_ohf"].estado is Estado.ROJO
    assert acta["sonda_ohf_on_safety_mode"].estado is Estado.ROJO


def test_un_429_es_averia_del_instrumento_y_no_fallo_del_producto():
    """Distinguirlos no es cosmética: un instrumento que acusa al producto de su
    propia avería es peor que no medir.

    Pasó en la primera corrida contra Sonnet: 25 minutos de backoff sin una sola
    respuesta, y el arnés lo reportaba como `AssertionError` —la misma excepción
    con la que fallan los criterios reales—. La fixture lo traduce a un mensaje
    que dice explícitamente que el eval no llegó a medir.
    """
    from tests.evals.stakeholder_sim import AveriaDelInstrumento, _run_with_backoff

    class ProveedorSaturado:
        """Devuelve siempre un 429 en el contenido, que es como agno los expone."""

        class _Salida:
            content = "Error code: 429 - {'type': 'rate_limit_error'}"

        def run(self, *_a, **_k):
            return self._Salida()

    import tests.evals.stakeholder_sim as sim

    original = sim._BACKOFF_SCHEDULE_S
    sim._BACKOFF_SCHEDULE_S = (0,)  # sin esperas reales
    try:
        with pytest.raises(AveriaDelInstrumento) as exc:
            _run_with_backoff(ProveedorSaturado(), "hola", "sid")
    finally:
        sim._BACKOFF_SCHEDULE_S = original
    assert "no llegó a medir" in str(exc.value)
    assert not isinstance(exc.value, AssertionError)
