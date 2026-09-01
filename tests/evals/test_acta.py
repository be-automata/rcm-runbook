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
        # (turno, fase, faltantes): un intento de cierre legítimo, en fase 6 y sin
        # faltantes. La sonda de export prematuro añade sus propios intentos en las
        # pruebas que la ejercitan.
        "intentos_de_export": [(40, 6, 0)],
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
    # Se quita el modo Y todo lo que colgaba de él: una sesión real no puede tener
    # una decisión ni una tarea para un modo que no existe — `_require` lo impide.
    del rota.failure_modes["FM-002"]
    for coleccion in (rota.effects, rota.controls, rota.risk_scores, rota.residual_scores,
                      rota.decisions, rota.actions, rota.tasks):
        coleccion.pop("FM-002", None)
    acta = _acta_de(rota, escenario, transcript_con_sondas)
    assert acta["modos_del_escenario_presentes"].estado is Estado.ROJO
    assert "FM-002" in acta["modos_del_escenario_presentes"].evidencia


def test_no_llegar_a_intentar_el_entregable_es_rojo(
    sesion_buena, escenario, transcript_con_sondas
):
    acta = _acta_de(sesion_buena, escenario, transcript_con_sondas,
                    herramientas_usadas=set(), intentos_de_export=[])
    assert acta["intento_export_definitivo"].estado is Estado.ROJO


def test_el_export_de_la_sonda_prematura_no_cuenta_como_intento_de_cierre(
    sesion_buena, escenario, transcript_con_sondas
):
    """El defecto que tenía este criterio al escribirlo.

    La sonda `premature_export` le pide al agente exportar en la fase 1. Si el
    criterio sólo mira «¿se llamó a export_excel alguna vez?», esa llamada —que el
    agente hace para ser correctamente rechazado— lo pone verde sin que el análisis
    haya avanzado nada. Un intento de cierre es una llamada con el análisis ya
    terminado, no cualquier llamada.
    """
    acta = _acta_de(sesion_buena, escenario, transcript_con_sondas,
                    intentos_de_export=[(2, 1, 12)])
    assert acta["intento_export_definitivo"].estado is Estado.ROJO
    assert "análisis abierto" in acta["intento_export_definitivo"].evidencia


def test_un_volcado_sin_el_registro_por_turno_no_se_da_por_bueno(
    sesion_buena, escenario, transcript_con_sondas
):
    """Compatibilidad honesta con volcados anteriores al registro por turno: no se
    puede afirmar que hubo cierre, así que queda sin evaluar en vez de verde."""
    acta = _acta_de(sesion_buena, escenario, transcript_con_sondas,
                    intentos_de_export=None)
    assert acta["intento_export_definitivo"].estado is Estado.NO_EVALUABLE


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


def test_el_estandar_debe_traer_los_numeros_del_escenario_no_un_digito_cualquiera(
    sesion_buena, escenario, transcript_con_sondas
):
    """La sonda `vague_standard` mide si el facilitador RECUPERÓ el estándar
    cuantitativo tras el rechazo — no si quedó alguno vago, porque eso ya lo
    impide el validador de `Function` y el criterio sería vacuo.

    Comparar dígitos sueltos dejaba pasar '1 bar' como si fuera '250 m³/h a 12
    bar'. Se comparan los números.
    """
    rota = sesion_buena.model_copy(deep=True)
    primaria = next(f for f in rota.functions.values() if f.kind.value == "primaria")
    rota.functions[primaria.id] = primaria.model_copy(
        update={"performance_standard": "1 bar, más o menos"}
    )
    acta = _acta_de(rota, escenario, transcript_con_sondas)
    assert acta["sonda_vague_standard"].estado is Estado.ROJO, acta.informe()


def test_cada_sonda_que_actua_sobre_un_modo_declara_cual(escenario):
    """El acoplamiento sonda→modo vive en el YAML, no en el orden de la lista.

    Antes el acta leía `failure_modes[0]` y `[1]`: reordenar el escenario habría
    hecho que dos sondas midieran el modo equivocado en silencio.
    """
    from tests.evals.acta import _modo_de_la_sonda

    sondas = {p["id"]: p for p in escenario["adversarial_probes"]}
    refs = {fm["ref"] for fm in escenario["failure_modes"]}
    for sid in ("cause_restates_mode", "effect_maintenance_assumption"):
        ref = sondas[sid].get("failure_mode_ref")
        assert ref in refs, f"la sonda {sid} no declara sobre qué modo actúa"
        assert _modo_de_la_sonda(escenario, sondas, sid) is not None


def test_un_volcado_viejo_no_acusa_al_producto_de_no_haber_exportado():
    """«El volcado no trae el dato» y «hubo cero intentos» no son lo mismo.

    Al releer una corrida anterior al registro por turno, `datos.get(k) or []`
    colapsaba ambos casos y el criterio salía ROJO sobre una sesión que sí había
    exportado. Un instrumento que acusa al producto de su propia laguna es el
    mismo defecto que el 429 reportado como AssertionError.
    """
    from tests.evals.stakeholder_sim import ResultadoEval, load_scenario

    escenario = load_scenario()
    viejo = ResultadoEval.desde_json({"herramientas_usadas": ["export_excel"]}, escenario)
    assert viejo.intentos_de_export is None
    nuevo = ResultadoEval.desde_json({"intentos_de_export": []}, escenario)
    assert nuevo.intentos_de_export == []


def test_el_volcado_dice_que_modelo_lo_produjo_y_donde_vive(escenario):
    """Dos lecciones que costaron caro, cerradas con un test.

    Un acta que no dice qué modelo midió no se puede interpretar: una tanda entera
    se midió contra Haiku creyendo que era Sonnet. Y el primer volcado se escribió
    en un temporal del sistema y se perdió con la limpieza — veinte minutos y un
    millón de tokens de evidencia, borrados por el sitio donde los dejé.
    """
    from tests.evals.conftest import DIRECTORIO_DE_ARTEFACTOS
    from tests.evals.stakeholder_sim import ResultadoEval

    r = ResultadoEval(session=None, scenario=escenario, modelo="claude-sonnet-4-5")
    assert r.como_json()["modelo"] == "claude-sonnet-4-5"
    assert ResultadoEval.desde_json(r.como_json(), escenario).modelo == "claude-sonnet-4-5"

    partes = DIRECTORIO_DE_ARTEFACTOS.parts
    assert "tmp" not in partes and "temp" not in partes, DIRECTORIO_DE_ARTEFACTOS
    assert partes[-2:] == ("data", "evals"), DIRECTORIO_DE_ARTEFACTOS


class TestElGuionDelSimulador:
    """El simulador no puede cumplir una instrucción condicionada a algo que no ve.

    Su guion dice «lanza cada sonda en la fase que indica su campo `phase`», pero la
    fase es estado del FACILITADOR. La primera corrida real lanzó cero de cinco
    sondas en veinte turnos: la condición era inobservable. El arnés ya leía la fase
    en cada turno para otras cosas; ahora se la pasa.
    """

    def test_en_fase_1_solo_toca_la_sonda_de_fase_1(self, escenario):
        from tests.evals.stakeholder_sim import _guion_pendiente

        texto = _guion_pendiente(escenario, [], fase_actual=1)
        assert "FASE 1" in texto
        assert "premature_export" in texto
        toca = texto.split("TE TOCA LANZAR YA")[1]
        assert "vague_standard" not in toca and "ohf_on_safety_mode" not in toca

    def test_al_avanzar_la_fase_se_acumulan_las_pendientes(self, escenario):
        from tests.evals.stakeholder_sim import _guion_pendiente

        toca = _guion_pendiente(escenario, [], fase_actual=5).split("TE TOCA LANZAR YA")[1]
        for sid in ("premature_export", "vague_standard", "cause_restates_mode",
                    "ohf_on_safety_mode"):
            assert sid in toca, sid

    def test_una_sonda_ya_lanzada_deja_de_pedirse(self, escenario):
        """Sin esto, Carlos repetiría la misma sonda cada turno."""
        from tests.evals.stakeholder_sim import _guion_pendiente

        sonda = next(p for p in escenario["adversarial_probes"] if p["id"] == "premature_export")
        texto = _guion_pendiente(escenario, [f"[CARLOS t2] {sonda['utterance']}"], fase_actual=1)
        assert "premature_export" not in texto.split("- Modos")[0] + texto.split("\n")[-1]

    def test_un_modo_ya_mencionado_deja_de_pedirse(self, escenario):
        from tests.evals.stakeholder_sim import _guion_pendiente

        dicho = "[CARLOS t3] El presostato PSL-101 se queda sin respuesta ante la caída de succión"
        texto = _guion_pendiente(escenario, [dicho], fase_actual=3)
        linea = next(x for x in texto.splitlines() if x.startswith("- Modos"))
        assert "FM-003" not in linea and "FM-001" in linea


def test_se_mide_si_consulto_el_catalogo_iso(sesion_buena, escenario, transcript_con_sondas):
    """El criterio que permite verificar el arreglo de los códigos ISO.

    Antes de esto el acta no observaba la conducta que la regla pide, así que una
    corrida no podía decir si el arreglo funcionó. Mide y no vota: el campo es un
    enum —un código inventado nunca llega al estado— y una sesión donde el
    interesado dicta los códigos correctos es legítima.
    """
    acta = _acta_de(sesion_buena, escenario, transcript_con_sondas,
                    herramientas_usadas={"export_excel", "lookup_iso14224"})
    c = acta["consulto_el_catalogo_iso"]
    assert c.estado is Estado.MEDIDO and not c.obligatorio
    assert "lookup_iso14224" in c.evidencia

    sin_consultar = _acta_de(sesion_buena, escenario, transcript_con_sondas,
                             herramientas_usadas={"export_excel"})
    assert "de memoria" in sin_consultar["consulto_el_catalogo_iso"].evidencia
    # Y no tumba la corrida: sigue sin haber rojos.
    assert not sin_consultar.rojos(), sin_consultar.informe()


def test_el_saldo_agotado_aborta_en_vez_de_quemar_ochenta_turnos():
    """El caso que se escapó, y costó una corrida entera de lectura equivocada.

    La detección sólo miraba 429. Un saldo agotado llega como **400** con
    «Your credit balance is too low», así que el arnés lo tomó por una respuesta
    normal: 80 turnos, cero modos registrados, y SIETE criterios en rojo contra el
    facilitador por una cuenta vacía.

    Y hay algo peor que el falso rojo: esperar no arregla un saldo. Reintentar con
    backoff habría gastado 25 minutos garantizando el mismo resultado.
    """
    from tests.evals.stakeholder_sim import AveriaDelInstrumento, _run_with_backoff

    class SinSaldo:
        class _Salida:
            content = (
                "Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', "
                "'message': 'Your credit balance is too low to access the Anthropic API. "
                "Please go to Plans & Billing to upgrade or purchase credits.'}}"
            )

        def __init__(self):
            self.llamadas = 0

        def run(self, *_a, **_k):
            self.llamadas += 1
            return self._Salida()

    agente = SinSaldo()
    with pytest.raises(AveriaDelInstrumento) as exc:
        _run_with_backoff(agente, "hola", "sid")
    assert "no llegó a medir" in str(exc.value)
    assert agente.llamadas == 1, "no debe reintentar lo que no se arregla esperando"


def test_el_producto_y_el_arnes_usan_la_misma_lista_de_averias():
    """Dos listas de patrones es cómo se llega a que el producto reconozca una
    avería del proveedor y el instrumento no. Pasó: `app.py` distinguía saldo de
    saturación desde la ronda 27, y el arnés seguía mirando sólo 429."""
    import inspect as _inspect

    from tests.evals import stakeholder_sim

    fuente = _inspect.getsource(stakeholder_sim._averia_del_proveedor)
    assert "_FALLOS_DEL_PROVEEDOR" in fuente, "el arnés volvió a tener su propia lista"


class TestQueSeReintentaYQueNo:
    """La misma tabla decide si hay avería y si se arregla esperando.

    Arreglé la lista que DETECTA reusando `app._FALLOS_DEL_PROVEEDOR` y dejé
    duplicada la que CLASIFICA, con sus propias subcadenas. Ya había divergido:
    «429 too many requests» —que `app.py` trata como saturación— no lleva la
    literal `rate_limit_error`, así que se abortaba una corrida entera por algo
    que se arregla esperando. El mismo defecto, un nivel más abajo.
    """

    @pytest.mark.parametrize(
        "contenido,transitorio",
        [
            ("Error: 429 too many requests, please slow down", True),
            ("Error code: 429 - {'type':'rate_limit_error'}", True),
            ("{'type':'overloaded_error'}", True),
            ("Your credit balance is too low to access the Anthropic API.", False),
            ("{'type':'authentication_error'}", False),
            ("invalid x-api-key", False),
        ],
    )
    def test_cada_averia_se_clasifica_como_en_el_producto(self, contenido, transitorio):
        from rcm_runbook.app import _FALLOS_DEL_PROVEEDOR
        from tests.evals.stakeholder_sim import _averia_del_proveedor, _es_saturacion

        salida = type("S", (), {"content": contenido})()
        assert _averia_del_proveedor(salida), "no la reconoció como avería"
        assert _es_saturacion(salida) is transitorio
        # Y coincide con lo que el producto le diría al cliente.
        esperado = next(t for p, _m, t in _FALLOS_DEL_PROVEEDOR if p.search(contenido))
        assert esperado is transitorio

    def test_un_turno_normal_no_es_averia(self):
        from tests.evals.stakeholder_sim import _averia_del_proveedor

        salida = type("S", (), {"content": "El impulsor presenta desgaste erosivo."})()
        assert not _averia_del_proveedor(salida)

    def test_la_clasificacion_tampoco_tiene_lista_propia(self):
        """El gemelo del test que ya vigila `_averia_del_proveedor`. Faltaba éste,
        y por eso el defecto sobrevivió al arreglo anterior."""
        import inspect as _inspect

        from tests.evals import stakeholder_sim

        fuente = _inspect.getsource(stakeholder_sim._es_saturacion)
        assert "_FALLOS_DEL_PROVEEDOR" in fuente
        assert not hasattr(stakeholder_sim, "_SATURACION"), "volvió la lista paralela"

    def test_una_saturacion_si_se_reintenta(self):
        """El contrapunto: al arreglar el aborto indebido no se rompe el backoff."""
        import tests.evals.stakeholder_sim as sim
        from tests.evals.stakeholder_sim import _run_with_backoff

        class SaturadoYLuegoBien:
            def __init__(self):
                self.n = 0

            def run(self, *_a, **_k):
                self.n += 1
                texto = "429 too many requests" if self.n == 1 else "listo"
                return type("S", (), {"content": texto})()

        agente = SaturadoYLuegoBien()
        original = sim._BACKOFF_SCHEDULE_S
        sim._BACKOFF_SCHEDULE_S = (0,)
        try:
            salida = _run_with_backoff(agente, "hola", "sid")
        finally:
            sim._BACKOFF_SCHEDULE_S = original
        assert salida.content == "listo" and agente.n == 2
