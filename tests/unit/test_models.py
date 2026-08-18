"""Domain model validators + session aggregate invariants."""

import pytest
from pydantic import ValidationError

from rcm_runbook.models.catalogs import (
    ConsequenceClass,
    DataSource,
    FailurePattern,
    MaintenancePolicy,
)
from rcm_runbook.models.domain import (
    DecisionResult,
    RiskScore,
    TPEFEstimate,
)
from rcm_runbook.models.session import (
    Phase,
    RCMSession,
    ReferentialIntegrityError,
)


def make_session_with_mode(**fm_overrides) -> tuple[RCMSession, str]:
    s = RCMSession()
    fn = s.add_function(
        kind="primaria", verb="bombear", object="agua de proceso",
        performance_standard="120 m³/h a 6 bar",
    )
    ff = s.add_functional_failure(fn.id, "No alcanza el caudal requerido de 120 m³/h")
    fm_kwargs = dict(
        description="Cavitación por baja presión de succión",
        mechanism="Cavitación",
        iso_code="LOO",
        cause="Operación fuera de las condiciones de diseño",
        root_cause="Filtro de succión obstruido",
        failure_pattern=FailurePattern.ALEATORIA,
    )
    fm_kwargs.update(fm_overrides)
    fm = s.add_failure_mode(ff.id, **fm_kwargs)
    return s, fm.id


class TestFunctionValidators:
    def test_vague_standard_rejected(self):
        s = RCMSession()
        with pytest.raises(ValidationError, match="cuantitativo"):
            s.add_function(
                kind="primaria", verb="bombear", object="agua",
                performance_standard="bien",
            )

    def test_ids_are_sequential(self):
        s, _ = make_session_with_mode()
        f2 = s.add_function(
            kind="secundaria", verb="contener", object="el fluido",
            performance_standard="sin fugas visibles",
        )
        assert f2.id == "F-002"


class TestFailureModeValidators:
    def test_cause_restating_mode_rejected(self):
        s = RCMSession()
        fn = s.add_function(
            kind="primaria", verb="bombear", object="agua",
            performance_standard="120 m³/h",
        )
        ff = s.add_functional_failure(fn.id, "No bombea el caudal requerido")
        with pytest.raises(ValidationError, match="reformulación"):
            s.add_failure_mode(
                ff.id,
                description="Cavitación por baja presión de succión",
                mechanism="Cavitación",
                iso_code="LOO",
                cause="Cavitación por baja presión de succión",
                root_cause="NPSH insuficiente",
                failure_pattern=FailurePattern.ALEATORIA,
            )

    def test_unknown_iso_code_rejected(self):
        s = RCMSession()
        fn = s.add_function(
            kind="primaria", verb="bombear", object="agua", performance_standard="120 m³/h",
        )
        ff = s.add_functional_failure(fn.id, "No bombea")
        with pytest.raises(ValidationError, match="ISO 14224"):
            s.add_failure_mode(
                ff.id,
                description="Desgaste del impulsor por erosión",
                mechanism="Erosión",
                iso_code="XXX",
                cause="Sólidos en el fluido",
                root_cause="Filtración deficiente aguas arriba",
                failure_pattern=FailurePattern.FIN_DE_VIDA_UTIL,
            )

    def test_non_credible_requires_documented_discard(self):
        with pytest.raises(ValidationError, match="no creíble"):
            make_session_with_mode(credible=False, non_credible_discard="")

    def test_non_credible_with_discard_ok(self):
        s, fmid = make_session_with_mode(
            credible=False,
            non_credible_discard="Modo no aplicable: la bomba opera inundada, sin succión negativa",
        )
        assert s.failure_modes[fmid].credible is False


class TestEffectValidators:
    def test_maintenance_assumption_rejected(self):
        s, fmid = make_session_with_mode()
        with pytest.raises(ValidationError, match="NO se hace mantenimiento"):
            s.set_effect(
                fmid,
                local="Ruido hidráulico, pero la inspección lo detecta a tiempo",
                system="Pérdida de caudal en el lazo",
                plant="Reducción de producción",
                is_hidden=False,
                operational=True,
            )

    def test_hidden_with_evident_route_rejected(self):
        s, fmid = make_session_with_mode()
        with pytest.raises(ValidationError, match="oculta"):
            s.set_effect(
                fmid,
                local="Sin señal al operador",
                system="Protección indisponible",
                plant="Riesgo latente",
                is_hidden=True,
                evident_route="A",
                safety=True,
            )

    def test_requires_consequence_flag(self):
        s, fmid = make_session_with_mode()
        with pytest.raises(ValidationError, match="consecuencia"):
            s.set_effect(
                fmid,
                local="Ruido hidráulico",
                system="Pérdida de caudal",
                plant="Menor producción",
                is_hidden=False,
            )


class TestReferentialIntegrity:
    def test_out_of_order_effect_rejected_in_spanish(self):
        s = RCMSession()
        with pytest.raises(ReferentialIntegrityError, match="No existe modo de falla"):
            s.set_effect(
                "FM-999",
                local="x" * 6, system="y" * 6, plant="z" * 6,
                is_hidden=False, operational=True,
            )

    def test_ff_requires_existing_function(self):
        s = RCMSession()
        with pytest.raises(ReferentialIntegrityError, match="No existe función"):
            s.add_functional_failure("F-404", "No bombea nada de nada")

    def test_score_requires_existing_mode(self):
        s = RCMSession()
        with pytest.raises(ReferentialIntegrityError):
            s.set_risk_score(
                RiskScore(failure_mode_id="FM-1", severity=5, occurrence=5, detection=5)
            )


class TestStaleness:
    def _decided_session(self) -> tuple[RCMSession, str]:
        s, fmid = make_session_with_mode()
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
        return s, fmid

    def test_edit_after_decision_detected(self):
        s, fmid = self._decided_session()
        assert s.stale_decisions() == []
        # `root_cause` es descriptivo y decide() no lo lee; el patrón sí.
        s.update_failure_mode(fmid, pf_interval_hours=999.0)
        assert s.stale_decisions() == [fmid]

    def test_digest_flags_stale(self):
        s, fmid = self._decided_session()
        s.update_failure_mode(fmid, description="Cavitación severa por NPSH insuficiente")
        assert "desactualizadas" in s.digest_es()


class TestSerializationBoundary:
    def test_dump_load_dump_identity(self):
        s, fmid = make_session_with_mode()
        s.set_effect(
            fmid,
            local="Ruido hidráulico y vibración",
            system="Pérdida de caudal",
            plant="Parada de producción",
            is_hidden=False,
            operational=True,
        )
        s.failure_modes[fmid] = s.failure_modes[fmid].model_copy(
            update={"tpef": TPEFEstimate(value_hours=8760, fuente=DataSource.OREDA)}
        )
        dump1 = s.model_dump(mode="json")
        restored = RCMSession.model_validate(dump1)
        assert restored.model_dump(mode="json") == dump1
        assert restored.phase == Phase.P1_ALCANCE

    def test_schema_version_present(self):
        assert RCMSession().model_dump(mode="json")["schema_version"] == 1


class TestHITLLedger:
    def test_confirm_without_request_fails(self):
        s, fmid = make_session_with_mode()
        with pytest.raises(ReferentialIntegrityError, match="pendiente"):
            s.confirm_hitl(fmid, "ing. confiabilidad")

    def test_request_then_confirm(self):
        s, fmid = make_session_with_mode()
        s.request_hitl(fmid, "Consecuencia de seguridad")
        assert not s.hitl_confirmed(fmid)
        s.confirm_hitl(fmid, "supervisora HSE")
        assert s.hitl_confirmed(fmid)

    def test_request_is_idempotent(self):
        s, fmid = make_session_with_mode()
        s.request_hitl(fmid, "Consecuencia de seguridad")
        s.request_hitl(fmid, "Consecuencia de seguridad")
        assert len(s.hitl_ledger) == 1
