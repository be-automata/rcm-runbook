"""Phase gates, residual-S invariance, export blockers."""

from rcm_runbook.engine.compliance import check_gate, export_blockers, validate_ja1011
from rcm_runbook.models.catalogs import (
    ConsequenceClass,
    DataSource,
    FailurePattern,
    MaintenancePolicy,
)
from rcm_runbook.models.domain import (
    DecisionResult,
    MaintenanceTask,
    RecommendedAction,
    RiskScore,
    TPEFEstimate,
)
from rcm_runbook.models.session import KPI, Phase, RCMSession, ScopeMeta, TeamMember


def full_session() -> RCMSession:
    """Complete, gate-green session used as fixture (also by export golden tests)."""
    s = RCMSession()
    s.scope = ScopeMeta(
        equipment_family="Bomba Centrífuga",
        equipment_description="Bomba centrífuga de alimentación de agua de proceso",
        tag="P-201A",
        location="Planta de proceso, área 200",
        boundaries="Desde brida de succión hasta brida de descarga, incl. motor y acople",
        interfaces="Tanque T-200, colector de descarga",
        normal_conditions="Operación continua, 120 m³/h a 6 bar",
        objective="Optimizar el plan preventivo y reducir paradas no programadas",
        operating_context="Servicio continuo sin redundancia; parada = pérdida de producción",
    )
    s.team = [
        TeamMember(name="Ana", role="Mantenimiento mecánico"),
        TeamMember(name="Luis", role="Operaciones"),
    ]
    fn = s.add_function(
        kind="primaria", verb="bombear", object="agua de proceso",
        performance_standard="120 m³/h a 6 bar",
    )
    prot = s.add_function(
        kind="proteccion", verb="disparar", object="la bomba por alta temperatura",
        performance_standard="disparo a 85 °C en rodamientos",
    )
    from rcm_runbook.models.domain import FunctionKind

    s.confirm_no_functions_of_kind(FunctionKind.SECUNDARIA)
    ff = s.add_functional_failure(fn.id, "Caudal inferior a 120 m³/h")
    ff_prot = s.add_functional_failure(prot.id, "No dispara ante alta temperatura")

    fm1 = s.add_failure_mode(
        ff.id,
        description="Cavitación por baja presión de succión",
        mechanism="Cavitación",
        iso_code="LOO",
        cause="Operación fuera de las condiciones de diseño",
        root_cause="Filtro de succión obstruido",
        failure_pattern=FailurePattern.ALEATORIA,
        pf_interval_hours=2000,
        tpef=TPEFEstimate(value_hours=8760, fuente=DataSource.OREDA),
    )
    fm2 = s.add_failure_mode(
        ff_prot.id,
        description="Termocupla del rodamiento degradada sin señal",
        mechanism="Falla de Instrumentación",
        iso_code="AIR",
        cause="Envejecimiento",
        root_cause="Deriva del sensor por ciclos térmicos",
        failure_pattern=FailurePattern.FIN_DE_VIDA_UTIL,
        tpef=TPEFEstimate(value_hours=26280, fuente=DataSource.OPINION_EXPERTO),
    )
    s.set_effect(
        fm1.id,
        local="Ruido hidráulico, vibración creciente y daño del impulsor",
        system="Pérdida progresiva de caudal en el lazo de proceso",
        plant="Parada no programada y reducción de producción",
        is_hidden=False, operational=True, evident_route="B",
    )
    s.set_effect(
        fm2.id,
        local="Sin indicación de temperatura del rodamiento",
        system="Protección de disparo indisponible",
        plant="Riesgo de daño mayor del tren ante falla múltiple",
        is_hidden=True, safety=True, hidden_route="A",
    )
    s.add_control(fm1.id, kind="detectivo",
                  description="Ronda operativa diaria con lectura de presión")
    s.add_control(fm2.id, kind="preventivo", description="Calibración anual de instrumentos")

    for fmid, (sev, occ, det) in {fm1.id: (7, 5, 4), fm2.id: (9, 3, 8)}.items():
        snap = s.current_snapshot(fmid)
        s.set_risk_score(RiskScore(
            failure_mode_id=fmid, severity=sev, occurrence=occ, detection=det, input_hash=snap,
        ))

    s.set_decision(DecisionResult(
        failure_mode_id=fm1.id,
        consequence_class=ConsequenceClass.OPERACIONAL,
        policy=MaintenancePolicy.MBC,
        justification="Síntoma detectable con intervalo P-F de 2000 h; inspección cada 1000 h.",
        evident_route="B",
        input_hash=s.current_snapshot(fm1.id),
    ))
    s.request_hitl(fm2.id, "Consecuencia de seguridad en falla múltiple")
    s.confirm_hitl(fm2.id, "Supervisora HSE")
    s.set_decision(DecisionResult(
        failure_mode_id=fm2.id,
        consequence_class=ConsequenceClass.OCULTA,
        policy=MaintenancePolicy.BF,
        justification="Falla oculta de dispositivo de protección: prueba funcional (FFI).",
        hidden_route="A",
        hitl_confirmed_by="Supervisora HSE",
        input_hash=s.current_snapshot(fm2.id),
    ))
    s.add_action(RecommendedAction(
        failure_mode_id=fm1.id,
        what="Implementar monitoreo mensual de vibración y presión de succión",
        who="Predictivo", when="Mensual",
        verification="Tendencia de vibración estable y caudal dentro de especificación",
    ))
    s.add_action(RecommendedAction(
        failure_mode_id=fm2.id,
        what="Prueba funcional del disparo por alta temperatura",
        who="Instrumentista", when="Semestral",
        verification="Disparo simulado exitoso registrado en CMMS",
    ))
    s.add_task(MaintenanceTask(
        failure_mode_id=fm1.id,
        description="Análisis de vibraciones y verificación de presión de succión en P-201A",
        frequency="Mensual", duration_hours=2.0, discipline="Predictivo",
    ))
    s.add_task(MaintenanceTask(
        failure_mode_id=fm2.id,
        description="Prueba funcional del lazo de disparo por alta temperatura de rodamientos",
        frequency="Semestral", duration_hours=4.0, discipline="Instrumentista",
        requires_shutdown=True,
    ))
    s.kpis = [KPI(name="MTBF", target="> 8.760 h"),
              KPI(name="Cumplimiento del plan", target="> 95%")]
    s.review_triggers = ["Falla grave o repetitiva", "Cambio de condiciones operativas"]
    s.validation_signoff = "Validado por operaciones y mantenimiento el 2026-07-04"
    return s


class TestGates:
    def test_empty_session_blocks_p1_in_spanish(self):
        issues = check_gate(RCMSession(), Phase.P1_ALCANCE)
        assert issues and any("TAG" in i for i in issues)

    def test_p2_requires_protective_elicitation(self):
        s = RCMSession()
        s.add_function(kind="primaria", verb="bombear", object="agua",
                       performance_standard="120 m³/h a 6 bar")
        issues = check_gate(s, Phase.P2_FUNCIONES)
        assert any("PROTECCIÓN" in i for i in issues)

    def test_p2_explicit_none_confirmation_clears(self):
        s = RCMSession()
        fn = s.add_function(kind="primaria", verb="bombear", object="agua",
                            performance_standard="120 m³/h a 6 bar")
        s.add_functional_failure(fn.id, "No alcanza el caudal requerido")
        from rcm_runbook.models.domain import FunctionKind
        s.confirm_no_functions_of_kind(FunctionKind.SECUNDARIA)
        s.confirm_no_functions_of_kind(FunctionKind.PROTECCION)
        assert check_gate(s, Phase.P2_FUNCIONES) == []

    def test_full_session_all_gates_green(self):
        s = full_session()
        for phase in (Phase.P1_ALCANCE, Phase.P2_FUNCIONES, Phase.P3_AMEF,
                      Phase.P4_RIESGO, Phase.P5_DECISION, Phase.P6_PLAN):
            assert check_gate(s, phase) == [], f"gate {phase} not green"
        assert export_blockers(s) == []

    def test_missing_hitl_blocks_p5(self):
        s = full_session()
        fm2 = "FM-002"
        s.decisions[fm2] = s.decisions[fm2].model_copy(update={"hitl_confirmed_by": None})
        issues = check_gate(s, Phase.P5_DECISION)
        assert any("confirmación humana" in i for i in issues)

    def test_stale_decision_blocks_p5(self):
        s = full_session()
        s.update_failure_mode("FM-001", root_cause="Nivel bajo en tanque de succión")
        issues = check_gate(s, Phase.P5_DECISION)
        assert any("desactualizada" in i for i in issues)

    def test_missing_tpef_blocks_p6(self):
        s = full_session()
        s.failure_modes["FM-001"] = s.failure_modes["FM-001"].model_copy(update={"tpef": None})
        issues = check_gate(s, Phase.P6_PLAN)
        assert any("TPEF" in i for i in issues)

    def test_export_blockers_aggregate_incomplete_session(self):
        assert len(export_blockers(RCMSession())) > 3


class TestResidualInvariance:
    def test_residual_s_drop_without_redesign_blocked(self):
        s = full_session()
        s.set_risk_score(RiskScore(
            failure_mode_id="FM-001", severity=4, occurrence=3, detection=2, is_residual=True,
        ))
        issues = check_gate(s, Phase.P5_DECISION)
        assert any("severidad residual" in i for i in issues)

    def test_residual_s_drop_with_redesign_allowed(self):
        s = full_session()
        s.decisions["FM-001"] = s.decisions["FM-001"].model_copy(
            update={"policy": MaintenancePolicy.RD,
                    "justification": "Rediseño de la succión elimina la condición de cavitación."}
        )
        s.set_risk_score(RiskScore(
            failure_mode_id="FM-001", severity=4, occurrence=3, detection=2, is_residual=True,
        ))
        assert not any("severidad residual" in i for i in check_gate(s, Phase.P5_DECISION))

    def test_residual_o_d_improvement_always_allowed(self):
        s = full_session()
        s.set_risk_score(RiskScore(
            failure_mode_id="FM-001", severity=7, occurrence=2, detection=2, is_residual=True,
        ))
        assert not any("severidad residual" in i for i in check_gate(s, Phase.P5_DECISION))


class TestJA1011Audit:
    def test_full_session_clean(self):
        assert validate_ja1011(full_session()) == []

    def test_no_protective_functions_warns(self):
        s = RCMSession()
        s.add_function(kind="primaria", verb="bombear", object="agua",
                       performance_standard="120 m³/h")
        warnings = validate_ja1011(s)
        assert any("protección" in w for w in warnings)
