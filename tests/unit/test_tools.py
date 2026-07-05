"""Scripted non-UI session: drives all 6 phases through the real tool entrypoints
(P3a exit criterion). Also exercises Spanish error surfacing and gate refusals.
"""

from dataclasses import dataclass, field
from typing import Any

import pytest

from rcm_runbook.agent import tools as t


@dataclass
class FakeRunContext:
    session_state: dict[str, Any] = field(default_factory=dict)
    session_id: str = "test-session"


def call(tool_obj, ctx, **kwargs) -> str:
    """Invoke the underlying entrypoint of an agno @tool."""
    fn = getattr(tool_obj, "entrypoint", tool_obj)
    return fn(run_context=ctx, **kwargs)


@pytest.fixture
def ctx() -> FakeRunContext:
    return FakeRunContext()


class TestScriptedFullSession:
    def test_all_six_phases_to_export(self, ctx, tmp_path, monkeypatch):
        monkeypatch.setattr(t.settings, "exports_dir", str(tmp_path))

        # --- P1: alcance y contexto ---
        out = call(t.record_scope, ctx,
                   equipment_family="Bomba Centrífuga",
                   equipment_description="Bomba de alimentación de agua de proceso",
                   tag="P-201A", location="Área 200",
                   boundaries="De brida de succión a brida de descarga",
                   interfaces="Tanque T-200",
                   normal_conditions="Continuo, 120 m³/h a 6 bar",
                   objective="Optimizar plan preventivo",
                   operating_context="Sin redundancia; parada = pérdida de producción")
        assert out.startswith("✔") and "Alcance completo" in out
        call(t.record_team_member, ctx, name="Ana", role="Mantenimiento mecánico")
        call(t.record_team_member, ctx, name="Luis", role="Operaciones")
        out = call(t.advance_phase, ctx)
        assert "fase 2" in out

        # --- P2: funciones ---
        out = call(t.record_function, ctx, kind="primaria", verb="bombear",
                   object="agua de proceso", performance_standard="120 m³/h a 6 bar")
        assert "F-001" in out
        call(t.record_function, ctx, kind="proteccion", verb="disparar",
             object="la bomba por alta temperatura",
             performance_standard="disparo a 85 °C en rodamientos")
        call(t.confirm_no_functions, ctx, kind="secundaria")
        call(t.record_functional_failure, ctx, function_id="F-001",
             description="Caudal inferior a 120 m³/h")
        call(t.record_functional_failure, ctx, function_id="F-002",
             description="No dispara ante alta temperatura")
        assert "fase 3" in call(t.advance_phase, ctx)

        # --- P3: AMEF ---
        out = call(t.record_failure_mode, ctx,
                   functional_failure_id="FF-001",
                   description="Cavitación por baja presión de succión",
                   mechanism="Cavitación", iso_code="LOO",
                   cause="Operación fuera de las condiciones de diseño",
                   root_cause="Filtro de succión obstruido",
                   failure_pattern="Aleatoria",
                   pf_interval_hours=2000,
                   tpef_hours=8760, tpef_fuente="OREDA")
        assert "FM-001" in out
        call(t.record_failure_mode, ctx,
             functional_failure_id="FF-002",
             description="Termocupla del rodamiento degradada sin señal",
             mechanism="Falla de Instrumentación", iso_code="AIR",
             cause="Envejecimiento",
             root_cause="Deriva del sensor por ciclos térmicos",
             failure_pattern="Fin de Vida Útil",
             tpef_hours=26280, tpef_fuente="Opinión de experto")
        call(t.record_effect, ctx, failure_mode_id="FM-001",
             local="Ruido hidráulico y vibración creciente",
             system="Pérdida progresiva de caudal",
             plant="Parada no programada",
             is_hidden=False, operational=True)
        out = call(t.record_effect, ctx, failure_mode_id="FM-002",
                   local="Sin indicación de temperatura del rodamiento",
                   system="Protección de disparo indisponible",
                   plant="Daño mayor del tren ante falla múltiple",
                   is_hidden=True, safety=True)
        assert "OCULTA" in out
        call(t.record_control, ctx, failure_mode_id="FM-001", kind="detectivo",
             description="Ronda operativa diaria con lectura de presión")
        call(t.record_control, ctx, failure_mode_id="FM-002", kind="preventivo",
             description="Calibración anual de instrumentos")
        assert "fase 4" in call(t.advance_phase, ctx)

        # --- P4: riesgo ---
        out = call(t.score_risk, ctx, failure_mode_id="FM-001",
                   severity=7, occurrence=5, detection=4)
        assert "RPN=140" in out
        out = call(t.score_risk, ctx, failure_mode_id="FM-002",
                   severity=9, occurrence=3, detection=8)
        assert "SIEMPRE" in out  # high-severity caveat surfaced
        assert "fase 5" in call(t.advance_phase, ctx)

        # --- P5: decisión ---
        out = call(t.run_decision_logic, ctx, failure_mode_id="FM-001",
                   pf_interval_sufficient=True)
        assert "MBC" in out
        # Safety consequence → HITL required first
        out = call(t.run_decision_logic, ctx, failure_mode_id="FM-002",
                   failure_finding_feasible=True)
        assert "CONFIRMACIÓN HUMANA" in out
        out = call(t.run_decision_logic, ctx, failure_mode_id="FM-002",
                   failure_finding_feasible=True, approver="Supervisora HSE")
        assert "BF" in out
        out = call(t.calculate_ffi, ctx, method="single_single",
                   mtive_hours=87600, mted_hours=43800, mmf_hours=876000)
        assert "FFI" in out and "✔" in out
        call(t.record_action, ctx, failure_mode_id="FM-001",
             what="Implementar monitoreo mensual de vibración y presión de succión",
             who="Predictivo", when="Mensual",
             verification="Tendencia estable y caudal en especificación")
        call(t.record_action, ctx, failure_mode_id="FM-002",
             what="Prueba funcional del disparo por alta temperatura",
             who="Instrumentista", when="Semestral",
             verification="Disparo simulado exitoso en CMMS")
        assert "fase 6" in call(t.advance_phase, ctx)

        # --- P6: plan + gobernanza ---
        call(t.record_task, ctx, failure_mode_id="FM-001",
             description="Análisis de vibraciones y verificación de presión de succión",
             frequency="Mensual", duration_hours=2.0, discipline="Predictivo")
        call(t.record_task, ctx, failure_mode_id="FM-002",
             description="Prueba funcional del lazo de disparo por alta temperatura",
             frequency="Semestral", duration_hours=4.0, discipline="Instrumentista",
             requires_shutdown=True)
        call(t.record_governance, ctx,
             kpis="MTBF=> 8760 h; Cumplimiento del plan=> 95%",
             review_triggers="Falla grave o repetitiva; Cambio de condiciones",
             validation_signoff="Validado por operaciones y mantenimiento")

        # --- export ---
        out = call(t.export_excel, ctx)
        assert "✔ Entregable definitivo exportado" in out
        assert "AMEF_P-201A.xlsx" in out
        assert "/exports/test-session/" in out

    def test_premature_export_refused_with_deficiency_list(self, ctx):
        out = call(t.export_excel, ctx)
        assert out.startswith("❌")
        assert "Fase 1" in out

    def test_premature_advance_refused_in_spanish(self, ctx):
        out = call(t.advance_phase, ctx)
        assert out.startswith("❌") and "TAG" in out


class TestSpanishErrorSurfacing:
    def test_validation_error_no_traceback(self, ctx):
        out = call(t.record_function, ctx, kind="primaria", verb="bombear",
                   object="agua", performance_standard="bien")
        assert out.startswith("❌")
        assert "Traceback" not in out and "cuantitativo" in out

    def test_unknown_entity_in_spanish(self, ctx):
        out = call(t.record_effect, ctx, failure_mode_id="FM-404",
                   local="x" * 6, system="y" * 6, plant="z" * 6,
                   is_hidden=False, operational=True)
        assert "No existe modo de falla" in out

    def test_effect_with_maintenance_assumption_rejected(self, ctx):
        call(t.record_scope, ctx, tag="P-1")
        # need a mode first
        call(t.record_function, ctx, kind="primaria", verb="bombear",
             object="agua", performance_standard="120 m³/h")
        call(t.record_functional_failure, ctx, function_id="F-001",
             description="No alcanza el caudal")
        call(t.record_failure_mode, ctx, functional_failure_id="FF-001",
             description="Cavitación por baja presión de succión",
             mechanism="Cavitación", iso_code="LOO",
             cause="Operación fuera de condiciones de diseño",
             root_cause="Filtro obstruido", failure_pattern="Aleatoria")
        out = call(t.record_effect, ctx, failure_mode_id="FM-001",
                   local="Nada grave, la inspección lo detecta antes",
                   system="Sin impacto porque el preventivo lo cubre",
                   plant="Ninguno", is_hidden=False, operational=True)
        assert out.startswith("❌") and "NO se hace mantenimiento" in out

    def test_ohf_on_safety_mode_blocked(self, ctx):
        call(t.record_function, ctx, kind="primaria", verb="contener",
             object="fluido de proceso", performance_standard="sin fugas visibles")
        call(t.record_functional_failure, ctx, function_id="F-001",
             description="Fuga externa de proceso")
        call(t.record_failure_mode, ctx, functional_failure_id="FF-001",
             description="Fuga del sello mecánico por operación en seco",
             mechanism="Fuga", iso_code="ELP",
             cause="Error de Operación",
             root_cause="Arranque sin venteo", failure_pattern="Aleatoria")
        call(t.record_effect, ctx, failure_mode_id="FM-001",
             local="Derrame de fluido en el área",
             system="Exposición de personal a fluido presurizado",
             plant="Incidente de seguridad reportable",
             is_hidden=False, safety=True)
        # tolerable=True must NOT produce OHF for a safety mode
        out = call(t.run_decision_logic, ctx, failure_mode_id="FM-001",
                   consequences_tolerable=True, approver="Supervisor HSE")
        assert "OHF" not in out.split("Justificación")[0]


class TestLookups:
    def test_iso_catalog(self, ctx):
        out = call(t.lookup_iso14224, ctx, query="LOO")
        assert "Baja salida" in out

    def test_sod_anchor(self, ctx):
        out = call(t.lookup_sod_table, ctx, dimension="severidad", value=8)
        assert "no funciona" in out

    def test_handbook(self, ctx):
        out = call(t.consult_handbook, ctx, query="intervalo P-F inspección")
        assert "P-F" in out
