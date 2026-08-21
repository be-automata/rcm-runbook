"""La sesión real de UAT como ancla del motor. Determinista, en CI, coste cero.

Por qué existe
--------------
Al rediseñar el eval largo se relajaron cosas a propósito: `validate_ja1011` pasó
a medición, el recuento exacto de políticas dejó de votar, y `blockers == 0` se
sustituyó por criterios más finos. El riesgo real de esa relajación no es que el
eval deje de cazar al modelo —para eso están los mutantes de
`tests/evals/test_acta.py`— sino que alguien relaje **las reglas del motor** sin
que nada se queje.

Esto lo impide. Congela la forma de una sesión real, conducida por un ingeniero de
mantenimiento durante ~78 turnos: 63 modos, 60 creíbles, seis fases de las que
cerró cuatro. Extiende el patrón que ya usan `tests/export/test_trazabilidad.py` y
`tests/unit/test_resellar_decisiones.py` sobre este mismo fichero.

Qué NO es: un test del agente. No puede fallar porque el modelo empeore — no hay
modelo de por medio. Es un golden test del motor.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rcm_runbook.engine.compliance import (
    bloqueadores_por_clase,
    export_blockers,
    firma_es_identificable,
)
from rcm_runbook.models.session import RCMSession

FIXTURE = Path(__file__).parents[1] / "fixtures" / "uat_sesion_real.json"


@pytest.fixture(scope="module")
def sesion() -> RCMSession:
    return RCMSession.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))


def test_los_bloqueadores_se_reparten_en_dos_poblaciones(sesion):
    """57 de incompletitud y 2 de incoherencia.

    No es un detalle contable: admiten juicios opuestos. «Faltan 28 decisiones»
    dice que la sesión no terminó; «la prueba del presostato se agenda más
    espaciada que su propio intervalo calculado» dice que lo que sí se hizo está
    mal. Si alguien reclasifica y las mezcla, este test salta.
    """
    clases = bloqueadores_por_clase(sesion)
    assert len(export_blockers(sesion)) == 59
    assert len(clases["incompletitud"]) == 57
    assert len(clases["incoherencia"]) == 2
    assert {b.split()[2] for b in clases["incoherencia"]} == {"búsqueda"}


def test_la_incoherencia_viva_es_una_prueba_mas_lenta_que_su_intervalo(sesion):
    """FM-014 y FM-015: FFI de 526 h contra tarea 'Mensual' (730 h).

    El dispositivo de protección se prueba menos a menudo de lo que exige el
    cálculo de seguridad, sobre los dos únicos modos ocultos que llevan firma.
    Queda anotado aquí porque es un hallazgo abierto del análisis real, no un
    problema del motor: el motor lo detecta bien, que es lo que se comprueba.
    """
    incoherencias = bloqueadores_por_clase(sesion)["incoherencia"]
    afectados = {b for b in incoherencias if "FM-014" in b or "FM-015" in b}
    assert len(afectados) == 2, incoherencias
    assert all("526 h" in b for b in afectados)


def test_las_cuatro_primeras_fases_cerraron_sin_un_solo_faltante(sesion):
    """La sesión real no falló conduciendo: falló en volumen y en cierre.

    Cobertura exacta a escala real —60 modos creíbles, 60 efectos, 60
    valoraciones, ninguno huérfano— y cero bloqueadores de las fases 1 a 4. Ese
    es el modo de fallo de producción, y el escenario de juguete de 4 modos es
    estructuralmente incapaz de exhibirlo.
    """
    creibles = [fm for fm in sesion.failure_modes.values() if fm.credible]
    assert len(sesion.failure_modes) == 63
    assert len(creibles) == 60
    assert len(sesion.effects) == 60
    assert len(sesion.risk_scores) == 60
    tempranos = [
        b for b in export_blockers(sesion)
        if any(b.startswith(f"[Fase {n}]") for n in (1, 2, 3, 4))
    ]
    assert not tempranos, tempranos


def test_ningun_modo_oculto_quedo_en_operar_hasta_la_falla(sesion):
    """La barrera de JA1011 que no se negocia: un fallo oculto no se deja correr."""
    ocultos = [fmid for fmid, e in sesion.effects.items() if e.is_hidden]
    assert len(ocultos) == 11
    en_ohf = [
        f for f in ocultos
        if (d := sesion.decisions.get(f)) is not None and d.policy.value == "OHF"
    ]
    assert not en_ohf, en_ohf


def test_toda_confirmacion_humana_del_analisis_real_nombra_a_alguien(sesion):
    """El guardia de `run_decision_logic` no invalida el trabajo ya hecho.

    Las cuatro decisiones firmadas de la sesión real llevan nombre y cargo, así
    que exigir un firmante identificable no obliga a rehacer nada. (El libro mayor
    de este fixture guarda 'Integrante confirmante', pero es un artefacto de su
    anonimización: la decisión correspondiente sí trae el nombre.)
    """
    firmadas = {
        f: d.hitl_confirmed_by for f, d in sesion.decisions.items() if d.hitl_confirmed_by
    }
    assert firmadas, "el análisis real no tiene ninguna decisión con firma"
    genericas = {f: v for f, v in firmadas.items() if not firma_es_identificable(v)}
    assert not genericas, genericas


def test_los_modos_no_creibles_traen_su_descarte_documentado(sesion):
    """Un modo que nadie evaluó no deja rastro; uno descartado, sí — y el
    expediente tiene que poder distinguirlos."""
    no_creibles = [fm for fm in sesion.failure_modes.values() if not fm.credible]
    assert len(no_creibles) == 3
    sin_motivo = [fm.id for fm in no_creibles if not fm.non_credible_discard.strip()]
    assert not sin_motivo, sin_motivo


def test_el_eval_mide_el_modelo_que_se_despliega():
    """El eval no debe heredar el RCM_MODEL_ID del .env local.

    Pasó de verdad: el .env fijaba `claude-haiku-4-5` para abaratar el desarrollo
    mientras producción servía el default `claude-sonnet-4-5`, y una tanda entera
    de corridas midió el modelo equivocado sin que nada lo dijera. Un eval que mide
    otro modelo no mide el producto.
    """
    import tempfile
    from pathlib import Path

    from rcm_runbook.config import Settings
    from tests.evals.stakeholder_sim import _construye_settings_del_eval

    tmp = Path(tempfile.mkdtemp())
    cfg = _construye_settings_del_eval(tmp, tmp)
    assert cfg.model_id == Settings.model_fields["model_id"].default
    assert cfg.temperature == 0.0, "el sujeto bajo prueba debe medirse sin ruido de muestreo"
    assert cfg.add_datetime is False, "la fecha mete entropía en el prompt de cada corrida"


def test_el_eval_no_quema_la_ventana_de_la_suscripcion(monkeypatch):
    """Una conversación de 80 turnos agota la ventana de la suscripción, que se
    comparte con el trabajo interactivo. La primera corrida contra Sonnet se pasó
    25 minutos de backoff sin una sola respuesta mientras la misma petición por
    créditos respondía al instante: medir el producto no puede depender de una
    ventana que el trabajo del día agota."""
    import tempfile
    from pathlib import Path

    import tests.evals.stakeholder_sim as sim
    from tests.evals.stakeholder_sim import _construye_settings_del_eval

    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth-test")
    monkeypatch.delenv("RCM_EVAL_USAR_SUSCRIPCION", raising=False)
    assert _construye_settings_del_eval(tmp, tmp).claude_code_oauth_token == ""

    # …salvo que se pida explícitamente lo contrario.
    monkeypatch.setenv("RCM_EVAL_USAR_SUSCRIPCION", "1")
    assert _construye_settings_del_eval(tmp, tmp).claude_code_oauth_token == "oauth-test"

    # Y sin clave de API en ninguna parte no hay nada que preferir: suscripción.
    # Se neutraliza el rescate desde el .env del proyecto, que en esta máquina sí
    # tiene clave; lo que se prueba es el caso «no hay credencial de API».
    monkeypatch.delenv("RCM_EVAL_USAR_SUSCRIPCION")
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setattr(sim, "_cargar_env_del_proyecto", lambda: None)
    assert _construye_settings_del_eval(tmp, tmp).claude_code_oauth_token == "oauth-test"


# --- La partición no puede inventarse bloqueadores que no existen -----------


def _sesion_con_severidad_residual_menor(credible: bool, con_decision: bool):
    """Un modo cuya severidad residual bajó sin rediseño: incoherencia de manual."""
    from rcm_runbook.engine.decision_logic import DecisionAnswers, decide
    from rcm_runbook.models.domain import FunctionKind, RiskScore

    s = RCMSession()
    s.add_function(kind=FunctionKind.PRIMARIA, verb="bombear", object="crudo estabilizado",
                   performance_standard="250 m3/h a 12 bar")
    s.add_functional_failure(function_id="F-001", description="No entrega caudal alguno")
    s.add_failure_mode(
        functional_failure_id="FF-001",
        description="Rotura del eje por defecto de material", mechanism="Falla de Material",
        iso_code="BRD", cause="Defecto de fabricacion en la forja",
        root_cause="Control de calidad insuficiente del proveedor",
        failure_pattern="Mortalidad Infantil", credible=True,
    )
    s.set_effect(failure_mode_id="FM-001", local="Vibracion creciente",
                 system="Parada de la bomba", plant="Perdida de despacho",
                 is_hidden=False, operational=True)
    s.set_risk_score(RiskScore(failure_mode_id="FM-001", severity=8, occurrence=3, detection=4))
    s.set_risk_score(RiskScore(failure_mode_id="FM-001", severity=3, occurrence=3,
                               detection=4, is_residual=True))
    if con_decision:
        fm, ef = s.failure_modes["FM-001"], s.effects["FM-001"]
        s.set_decision(decide(fm, ef, DecisionAnswers(pf_interval_sufficient=True)))
    if not credible:
        s.failure_modes["FM-001"] = s.failure_modes["FM-001"].model_copy(
            update={"credible": False,
                    "non_credible_discard": "Eje sobredimensionado; 12 anios sin indicios"}
        )
    return s


@pytest.mark.parametrize(
    "credible,con_decision",
    [(False, True), (False, False), (True, False), (True, True)],
)
def test_la_incoherencia_nunca_sale_de_los_bloqueadores_reales(credible, con_decision):
    """`bloqueadores_de_incoherencia` es un SUBCONJUNTO de `export_blockers`.

    La primera versión reconstruía el criterio de la compuerta en vez de filtrar lo
    que emite, y divergía en dos condiciones que `_gate_p5` aplica: sólo mira modos
    creíbles, y hace `continue` antes del residual cuando el modo aún no tiene
    decisión. Salían incoherencias que no bloqueaban nada — rompiendo la partición
    y pudiendo poner en rojo el criterio obligatorio `cero_incoherencias` del eval
    por un motivo espurio.
    """
    from rcm_runbook.engine.compliance import bloqueadores_de_incoherencia

    s = _sesion_con_severidad_residual_menor(credible, con_decision)
    inventadas = set(bloqueadores_de_incoherencia(s)) - set(export_blockers(s))
    assert not inventadas, inventadas


@pytest.mark.parametrize(
    "credible,con_decision",
    [(False, True), (False, False), (True, False), (True, True)],
)
def test_las_dos_clases_particionan_exactamente(credible, con_decision):
    """Ni se pierde ni se duplica un bloqueador al clasificarlo."""
    s = _sesion_con_severidad_residual_menor(credible, con_decision)
    clases = bloqueadores_por_clase(s)
    assert (
        len(clases["incoherencia"]) + len(clases["incompletitud"]) == len(export_blockers(s))
    )
    assert not set(clases["incoherencia"]) & set(clases["incompletitud"])


def test_un_modo_creible_y_decidido_si_delata_su_severidad_residual():
    """El contrapunto: al arreglar el falso positivo no se pierde el verdadero."""
    from rcm_runbook.engine.compliance import bloqueadores_de_incoherencia

    s = _sesion_con_severidad_residual_menor(credible=True, con_decision=True)
    assert any("severidad residual" in b for b in bloqueadores_de_incoherencia(s))
