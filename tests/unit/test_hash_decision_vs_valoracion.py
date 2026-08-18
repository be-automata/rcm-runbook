"""Un hash cubre los insumos de SU artefacto.

Spec: `specs/hash-de-decision-y-de-valoracion.md`.

Los controles justifican la Detección (insumo de la valoración) y no entran en
`decision_logic.decide(fm, effect, answers)` (no son insumo de la decisión).
Sellar los dos artefactos con la misma fórmula marcaba como obsoletas 31 de las
32 decisiones de la sesión de UAT por un dato que no puede cambiar su política.

Los criterios 4 y 5 van en pareja a propósito: uno comprueba lo que debe dejar
de importar, el otro enumera insumo por insumo lo que tiene que seguir
importando. Partir un hash es fácil de hacer de más y dejarlo insensible a todo,
y un sello que no se rompe nunca no protege nada.
"""

from __future__ import annotations

import pytest

from rcm_runbook.models.catalogs import (
    ConsequenceClass,
    FailurePattern,
    MaintenancePolicy,
)
from rcm_runbook.models.domain import DecisionResult, RiskScore

from .test_models import make_session_with_mode


def _sesion_valorada_y_decidida(**fm_overrides):
    """Un modo con efecto, valoración y decisión, los dos sellos al día."""
    s, fmid = make_session_with_mode(**fm_overrides)
    s.set_effect(
        fmid,
        local="Ruido hidráulico y vibración",
        system="Pérdida progresiva de caudal",
        plant="Parada no programada",
        is_hidden=False,
        operational=True,
    )
    s.set_risk_score(
        RiskScore(
            failure_mode_id=fmid, severity=7, occurrence=5, detection=4,
            input_hash=s.score_snapshot(fmid),
        )
    )
    s.set_decision(
        DecisionResult(
            failure_mode_id=fmid,
            consequence_class=ConsequenceClass.OPERACIONAL,
            policy=MaintenancePolicy.MBC,
            justification="Síntoma detectable con intervalo P-F suficiente para inspección.",
            input_hash=s.decision_snapshot(fmid),
        )
    )
    assert s.stale_scores() == []
    assert s.stale_decisions() == []
    return s, fmid


class TestCriterio3LaValoracionSigueProtegida:
    """Añadir un control marca la valoración como obsoleta. Es lo que el hash
    original sí protegía y no se puede perder al partirlo."""

    def test_un_control_nuevo_ensucia_la_valoracion(self):
        s, fmid = _sesion_valorada_y_decidida()
        s.add_control(fmid, kind="detectivo", description="Ronda operativa diaria de presión")
        assert s.stale_scores() == [fmid]

    def test_un_control_nuevo_sobre_una_lista_que_ya_tenia_uno_tambien(self):
        s, fmid = _sesion_valorada_y_decidida()
        s.add_control(fmid, kind="detectivo", description="Ronda operativa diaria de presión")
        s.set_risk_score(
            RiskScore(
                failure_mode_id=fmid, severity=7, occurrence=5, detection=4,
                input_hash=s.score_snapshot(fmid),
            )
        )
        assert s.stale_scores() == []
        s.add_control(fmid, kind="preventivo", description="Calibración anual del transmisor")
        assert s.stale_scores() == [fmid]

    def test_el_mismo_control_repetido_no_ensucia_nada(self):
        s, fmid = _sesion_valorada_y_decidida()
        s.add_control(fmid, kind="detectivo", description="Ronda operativa diaria de presión")
        s.set_risk_score(
            RiskScore(
                failure_mode_id=fmid, severity=7, occurrence=5, detection=4,
                input_hash=s.score_snapshot(fmid),
            )
        )
        s.add_control(fmid, kind="detectivo", description="Ronda operativa diaria de presión")
        assert s.stale_scores() == []


class TestCriterio4LaDecisionDejaDeSerSensibleALosControles:
    def test_un_control_nuevo_no_ensucia_la_decision(self):
        s, fmid = _sesion_valorada_y_decidida()
        s.add_control(fmid, kind="detectivo", description="Ronda operativa diaria de presión")
        assert s.stale_decisions() == []

    def test_ni_un_segundo_control(self):
        s, fmid = _sesion_valorada_y_decidida()
        s.add_control(fmid, kind="detectivo", description="Ronda operativa diaria de presión")
        s.add_control(fmid, kind="preventivo", description="Calibración anual del transmisor")
        assert s.stale_decisions() == []

    def test_el_sello_de_la_decision_no_depende_de_los_controles(self):
        s, fmid = _sesion_valorada_y_decidida()
        antes = s.decision_snapshot(fmid)
        s.add_control(fmid, kind="mitigante", description="Bomba de respaldo en automático")
        assert s.decision_snapshot(fmid) == antes

    def test_y_el_de_la_valoracion_si(self):
        """La pareja del anterior: si los dos sellos empataran, uno de los dos
        estaría mal recortado."""
        s, fmid = _sesion_valorada_y_decidida()
        antes = s.score_snapshot(fmid)
        s.add_control(fmid, kind="mitigante", description="Bomba de respaldo en automático")
        assert s.score_snapshot(fmid) != antes


class TestCriterio5LaDecisionSigueSiendoSensibleALoQueSiLaAlimenta:
    """Un caso por insumo de `decide(fm, effect, answers)`."""

    def test_cambiar_el_efecto_ensucia_la_decision(self):
        s, fmid = _sesion_valorada_y_decidida()
        s.set_effect(
            fmid,
            local="Ruido hidráulico y vibración",
            system="Pérdida progresiva de caudal",
            plant="Riesgo de lesión al personal de operación",
            is_hidden=False,
            safety=True,
        )
        assert s.stale_decisions() == [fmid]

    def test_cambiar_el_patron_de_falla_ensucia_la_decision(self):
        s, fmid = _sesion_valorada_y_decidida()
        s.update_failure_mode(fmid, failure_pattern=FailurePattern.FIN_DE_VIDA_UTIL)
        assert s.stale_decisions() == [fmid]

    def test_cambiar_el_intervalo_pf_ensucia_la_decision(self):
        s, fmid = _sesion_valorada_y_decidida()
        s.update_failure_mode(fmid, pf_interval_hours=2000.0)
        assert s.stale_decisions() == [fmid]

    def test_cambiar_la_credibilidad_ensucia_la_decision(self):
        s, fmid = _sesion_valorada_y_decidida()
        s.update_failure_mode(
            fmid,
            credible=False,
            non_credible_discard="El equipo descartó el modo: no aplica a este servicio.",
        )
        assert s.stale_decisions() == [fmid]

    @pytest.mark.parametrize("campo,valor", [("weibull_eta_hours", 18000.0)])
    def test_el_resto_de_los_insumos_de_la_decision_tambien(self, campo, valor):
        s, fmid = _sesion_valorada_y_decidida()
        s.update_failure_mode(fmid, **{campo: valor})
        assert s.stale_decisions() == [fmid], f"'{campo}' salió del sello de la decisión"


class TestLosCamposDescriptivosNoEnsucianLaDecision:
    """`decide()` no los lee, así que no pueden cambiar la política.

    Sellarlos hacía que corregir una errata en la descripción marcara la
    decisión como obsoleta — y en los cuatro modos firmados de la sesión de UAT,
    que se volviera a pedir la firma JA1011 por una tilde. Se enumeraron contra
    el código: de `fm`, `decide()` sólo toca `failure_pattern`, `credible`,
    `pf_interval_hours` y `weibull_eta_hours`.

    Siguen sellados en la VALORACIÓN, que es donde sí pertenecen.
    """

    @pytest.mark.parametrize(
        ("campo", "valor"),
        [
            ("description", "Cavitación severa por NPSH insuficiente"),
            ("mechanism", "Erosión"),
            ("iso_code", "ERO"),
            ("cause", "Válvula de succión parcialmente cerrada"),
            ("root_cause", "Nivel bajo en el tanque de succión"),
            ("weibull_beta", 2.5),
        ],
    )
    def test_un_campo_descriptivo_no_ensucia_la_decision(self, campo, valor):
        s, fmid = _sesion_valorada_y_decidida()
        s.update_failure_mode(fmid, **{campo: valor})
        assert s.stale_decisions() == [], f"'{campo}' no lo lee decide(): no debe sellarse"

    @pytest.mark.parametrize(
        ("campo", "valor"),
        [("description", "Cavitación severa por NPSH insuficiente"), ("weibull_beta", 2.5)],
    )
    def test_pero_si_ensucia_la_valoracion(self, campo, valor):
        """La pareja del test de arriba: sale de un sello, no de los dos."""
        s, fmid = _sesion_valorada_y_decidida()
        s.update_failure_mode(fmid, **{campo: valor})
        assert s.stale_scores() == [fmid], f"'{campo}' tiene que seguir en el sello de la S/O/D"


class TestUnSelloHuerfanoNoRevientaElReporte:
    """Una valoración o una decisión de un modo que ya no está indexaba
    `failure_modes` y levantaba `KeyError` en mitad del digest y de las
    compuertas — o sea, en el sitio donde hay que poder seguir para reportar la
    inconsistencia. Se ignora; quién sobra no lo decide esta función."""

    def test_una_decision_huerfana_se_ignora(self):
        s, fmid = _sesion_valorada_y_decidida()
        s.decisions["FM-999"] = s.decisions[fmid].model_copy(
            update={"failure_mode_id": "FM-999", "input_hash": "sello-viejo"}
        )
        assert s.stale_decisions() == []
        assert "FM-999" not in s.digest_es()

    def test_una_valoracion_huerfana_se_ignora(self):
        s, fmid = _sesion_valorada_y_decidida()
        s.risk_scores["FM-999"] = s.risk_scores[fmid].model_copy(
            update={"failure_mode_id": "FM-999", "input_hash": "sello-viejo"}
        )
        assert s.stale_scores() == []


class TestCriterio7CadaMensajeDiceLaVerdad:
    def test_solo_la_valoracion_obsoleta_produce_solo_su_aviso(self):
        s, fmid = _sesion_valorada_y_decidida()
        s.add_control(fmid, kind="detectivo", description="Ronda operativa diaria de presión")
        digest = s.digest_es()
        assert "Valoraciones desactualizadas" in digest
        assert "Decisiones desactualizadas" not in digest

    def test_solo_la_decision_obsoleta_produce_solo_su_aviso(self):
        s, fmid = _sesion_valorada_y_decidida()
        s.update_failure_mode(fmid, pf_interval_hours=2000.0)
        # La valoración se re-sella: lo que se está probando es la decisión sola.
        s.set_risk_score(
            RiskScore(
                failure_mode_id=fmid, severity=7, occurrence=5, detection=4,
                input_hash=s.score_snapshot(fmid),
            )
        )
        digest = s.digest_es()
        assert "Decisiones desactualizadas" in digest
        assert "Valoraciones desactualizadas" not in digest

    def test_las_dos_obsoletas_producen_los_dos_avisos(self):
        s, fmid = _sesion_valorada_y_decidida()
        s.update_failure_mode(fmid, pf_interval_hours=2000.0)
        digest = s.digest_es()
        assert "Valoraciones desactualizadas" in digest
        assert "Decisiones desactualizadas" in digest

    def test_la_compuerta_p4_no_reclama_valoraciones_frescas(self):
        """El defecto de reporte: `stale_decisions()` devolvía la unión y P4 la
        etiquetaba como valoración obsoleta sobre scores perfectamente frescos."""
        from rcm_runbook.engine.compliance import check_gate
        from rcm_runbook.models.session import Phase

        s, fmid = _sesion_valorada_y_decidida()
        s.update_failure_mode(fmid, pf_interval_hours=2000.0)
        s.set_risk_score(
            RiskScore(
                failure_mode_id=fmid, severity=7, occurrence=5, detection=4,
                input_hash=s.score_snapshot(fmid),
            )
        )
        p4 = check_gate(s, Phase.P4_RIESGO)
        assert not [i for i in p4 if "valoración" in i and "desactualizada" in i]
        p5 = check_gate(s, Phase.P5_DECISION)
        assert [i for i in p5 if "La decisión del modo" in i and "desactualizada" in i]
