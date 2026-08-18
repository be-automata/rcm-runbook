"""Table-driven tests of the deterministic RCM decision cascade."""

import pytest

from rcm_runbook.engine.decision_logic import (
    DecisionAnswers,
    HITLRequired,
    classify_consequence,
    decide,
    decide_confirmed,
    derive_route,
)
from rcm_runbook.models.catalogs import (
    ConsequenceClass,
    EvidentRoute,
    FailurePattern,
    HiddenRoute,
    MaintenancePolicy,
)
from rcm_runbook.models.domain import Effect, FailureMode


def fm(**overrides) -> FailureMode:
    base = dict(
        id="FM-001",
        functional_failure_id="FF-001",
        description="Cavitación por baja presión de succión",
        mechanism="Cavitación",
        iso_code="LOO",
        cause="Operación fuera de las condiciones de diseño",
        root_cause="Filtro de succión obstruido",
        failure_pattern=FailurePattern.ALEATORIA,
    )
    base.update(overrides)
    return FailureMode(**base)


def effect(**overrides) -> Effect:
    base = dict(
        failure_mode_id="FM-001",
        local="Ruido hidráulico y vibración creciente",
        system="Pérdida progresiva de caudal",
        plant="Parada no programada del bombeo",
        is_hidden=False,
        operational=True,
    )
    base.update(overrides)
    return Effect(**base)


class TestConsequenceClassification:
    def test_hidden(self):
        e = effect(is_hidden=True, operational=False, safety=True)
        assert classify_consequence(e) == ConsequenceClass.OCULTA

    def test_safety_beats_operational(self):
        e = effect(safety=True)
        assert classify_consequence(e) == ConsequenceClass.SEGURIDAD_AMBIENTE

    def test_environment_is_se(self):
        e = effect(environment=True, operational=False, non_operational=False)
        assert classify_consequence(e) == ConsequenceClass.SEGURIDAD_AMBIENTE

    def test_non_operational(self):
        e = effect(operational=False, non_operational=True)
        assert classify_consequence(e) == ConsequenceClass.NO_OPERACIONAL


class TestCascade:
    def test_pf_sufficient_gives_mbc(self):
        result = decide(fm(pf_interval_hours=2000), effect(),
                        DecisionAnswers(pf_interval_sufficient=True))
        assert result.policy == MaintenancePolicy.MBC
        assert "P-F" in result.justification

    def test_insufficient_pf_skips_mbc(self):
        result = decide(
            fm(failure_pattern=FailurePattern.FIN_DE_VIDA_UTIL, weibull_eta_hours=10000),
            effect(),
            DecisionAnswers(pf_interval_sufficient=False, aging_related=True,
                            restoration_feasible=True),
        )
        assert result.policy == MaintenancePolicy.MBT
        assert "0.9" in result.justification or "9000" in result.justification

    def test_lubrication_aging_gives_rep(self):
        result = decide(
            fm(failure_pattern=FailurePattern.FIN_DE_VIDA_UTIL),
            effect(),
            DecisionAnswers(lubrication_related=True),
        )
        assert result.policy == MaintenancePolicy.REP

    def test_hidden_can_get_proactive_task(self):
        # Hidden modes may validly receive MBC when applicable — BF is the fallback, not forced
        result = decide(
            fm(pf_interval_hours=4000),
            effect(is_hidden=True, operational=True),
            DecisionAnswers(pf_interval_sufficient=True),
        )
        assert result.policy == MaintenancePolicy.MBC

    def test_hidden_fallback_is_bf(self):
        result = decide(
            fm(),
            effect(is_hidden=True, operational=True),
            DecisionAnswers(failure_finding_feasible=True),
        )
        assert result.policy == MaintenancePolicy.BF
        assert result.consequence_class == ConsequenceClass.OCULTA

    def test_hidden_se_nothing_applicable_requires_hitl_then_rd(self):
        f, e = fm(), effect(is_hidden=True, operational=False, safety=True)
        answers = DecisionAnswers()  # nothing applicable
        with pytest.raises(HITLRequired):
            decide(f, e, answers)
        result = decide_confirmed(f, e, answers, approver="supervisora HSE")
        assert result.policy == MaintenancePolicy.RD
        assert result.hitl_confirmed_by == "supervisora HSE"

    def test_evident_environmental_never_ohf(self):
        f, e = fm(), effect(environment=True, operational=False)
        answers = DecisionAnswers(consequences_tolerable=True)  # tolerable is irrelevant for SE
        with pytest.raises(HITLRequired):
            decide(f, e, answers)
        result = decide_confirmed(f, e, answers, approver="ing. ambiental")
        assert result.policy == MaintenancePolicy.RD

    def test_safety_requires_hitl_even_with_task(self):
        with pytest.raises(HITLRequired, match="SEGURIDAD"):
            decide(fm(pf_interval_hours=2000), effect(safety=True),
                   DecisionAnswers(pf_interval_sufficient=True))

    def test_confirmed_safety_with_task_keeps_task(self):
        result = decide_confirmed(
            fm(pf_interval_hours=2000), effect(safety=True),
            DecisionAnswers(pf_interval_sufficient=True), approver="HSE",
        )
        assert result.policy == MaintenancePolicy.MBC
        assert result.hitl_confirmed_by == "HSE"

    def test_tolerable_no_se_gives_ohf(self):
        result = decide(fm(), effect(operational=False, non_operational=True),
                        DecisionAnswers(consequences_tolerable=True))
        assert result.policy == MaintenancePolicy.OHF
        assert "documentada" in result.justification

    def test_non_credible_mode_refused(self):
        f = fm(credible=False,
               non_credible_discard="No aplicable: bomba opera inundada sin succión negativa")
        with pytest.raises(ValueError, match="descartado"):
            decide(f, effect(), DecisionAnswers())

    def test_justification_always_nonempty(self):
        cases = (
            (effect(), DecisionAnswers(pf_interval_sufficient=True)),
            (effect(is_hidden=True), DecisionAnswers(failure_finding_feasible=True)),
            (effect(), DecisionAnswers(consequences_tolerable=True)),
        )
        for e, answers in cases:
            result = decide(fm(), e, answers)
            assert len(result.justification) >= 15

    def test_all_false_answers_refuses_definitive_policy(self):
        """Engine must not invent BF/OHF when the team answered everything False."""
        with pytest.raises(ValueError, match="No hay política determinable"):
            decide(fm(), effect(), DecisionAnswers())
        with pytest.raises(ValueError, match="failure_finding_feasible"):
            decide(fm(), effect(is_hidden=True), DecisionAnswers())

    def test_automated_monitoring_rationale_without_pf_claim(self):
        """MBC via automated monitoring must not cite an insufficient P-F interval."""
        result = decide(
            fm(pf_interval_hours=48), effect(),
            DecisionAnswers(automated_monitoring_available=True,
                            pf_interval_sufficient=False),
        )
        assert result.policy == MaintenancePolicy.MBC
        assert "monitorización automatizado" in result.justification
        assert "P-F de 48" not in result.justification


class TestRouteDerivation:
    def test_evident_se_is_a(self):
        assert derive_route(effect(safety=True), MaintenancePolicy.MBC) == (EvidentRoute.A, None)

    def test_evident_operational_is_b(self):
        assert derive_route(effect(), MaintenancePolicy.MBC) == (EvidentRoute.B, None)

    def test_evident_ohf_is_d(self):
        e = effect(operational=False, non_operational=True)
        assert derive_route(e, MaintenancePolicy.OHF) == (EvidentRoute.D, None)

    def test_hidden_se_is_a(self):
        e = effect(is_hidden=True, safety=True, operational=False)
        assert derive_route(e, MaintenancePolicy.BF) == (None, HiddenRoute.A)

    def test_hidden_operational_is_e(self):
        e = effect(is_hidden=True)
        assert derive_route(e, MaintenancePolicy.BF) == (None, HiddenRoute.E)

    def test_decision_result_carries_route(self):
        result = decide(fm(pf_interval_hours=2000), effect(),
                        DecisionAnswers(pf_interval_sufficient=True))
        assert result.evident_route == EvidentRoute.B
        assert result.hidden_route is None
