"""Siembra la sesión de DEMO — caso real estilo benchmark del cliente.

Reproduce, con las herramientas reales del agente (sin LLM), un análisis RCM de la
bomba centrífuga P-03070 usando modos de falla tomados del AMEF benchmark del
cliente (cavitación LOO, fuga del sello ELP, protección PDE oculta, etc.) y deja:

  data/exports/demo/AMEF_P-03070.xlsx   ← entregable listo para mostrar (plan B)

Uso:  uv run python scripts/demo_seed.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rcm_runbook.agent import tools as t


@dataclass
class Ctx:
    session_state: dict[str, Any] = field(default_factory=dict)
    session_id: str = "demo"


def call(tool: Any, ctx: Ctx, **kwargs: Any) -> str:
    out = getattr(tool, "entrypoint", tool)(run_context=ctx, **kwargs)
    if out.startswith("❌") or "CONFIRMACIÓN" in out and "requerida" in out.lower():
        pass
    print(" ", out.splitlines()[0][:110])
    return out


def main() -> None:
    ctx = Ctx()
    t.settings.exports_dir = "data/exports"

    print("— P1: alcance y equipo")
    call(t.record_scope, ctx,
         equipment_family="Bomba Centrífuga",
         equipment_description="Bomba centrífuga de transferencia de crudo",
         tag="P-03070",
         location="Estación de flujo, patio de bombas",
         boundaries="De brida de succión a brida de descarga: motor, acople, bomba, "
                    "sello mecánico, instrumentación asociada",
         interfaces="Tanque de carga TK-101 y múltiple de descarga",
         normal_conditions="Servicio continuo, crudo 18 °API, 850 GPM @ 150 psi",
         objective="Optimizar el plan de mantenimiento y reducir paradas no programadas",
         operating_context="Sin redundancia instalada; una parada detiene la "
                           "transferencia de crudo de la estación")
    call(t.record_team_member, ctx, name="Carlos Mendoza", role="Mantenimiento mecánico")
    call(t.record_team_member, ctx, name="María Torres", role="Operaciones")
    call(t.record_team_member, ctx, name="José Rivas", role="Instrumentación")
    call(t.advance_phase, ctx)

    print("— P2: funciones")
    call(t.record_function, ctx, kind="primaria", verb="bombear",
         object="crudo hacia el múltiple de descarga",
         performance_standard="850 GPM a 150 psi de descarga")
    call(t.record_function, ctx, kind="secundaria", verb="contener",
         object="el crudo del proceso",
         performance_standard="sin fugas visibles al ambiente")
    call(t.record_function, ctx, kind="proteccion", verb="disparar",
         object="la bomba por baja presión de succión",
         performance_standard="disparo a presión < 5 psi en succión")
    call(t.record_functional_failure, ctx, function_id="F-001",
         description="No alcanza el caudal requerido de 850 GPM")
    call(t.record_functional_failure, ctx, function_id="F-002",
         description="Fuga externa de crudo al ambiente")
    call(t.record_functional_failure, ctx, function_id="F-003",
         description="No dispara ante baja presión de succión")
    call(t.advance_phase, ctx)

    print("— P3: AMEF (modos del benchmark del cliente)")
    call(t.record_failure_mode, ctx, functional_failure_id="FF-001",
         description="Cavitación por NPSH por debajo del requerido",
         mechanism="Cavitación", iso_code="LOO",
         cause="Operación fuera de las condiciones de diseño",
         root_cause="Nivel bajo del tanque de carga y filtro de succión obstruido",
         failure_pattern="Aleatoria", pf_interval_hours=1440,
         tpef_hours=8186, tpef_fuente="OREDA",
         tpef_note="TPEF genérico OREDA bombas centrífugas")
    call(t.record_failure_mode, ctx, functional_failure_id="FF-002",
         description="Fuga del sello mecánico por operación en seco",
         mechanism="Fuga", iso_code="ELP",
         cause="Error de Operación",
         root_cause="Arranque con succión cerrada tras mantenimiento",
         failure_pattern="Aleatoria/Fin de Vida Útil",
         tpef_hours=17520, tpef_fuente="Historial CMMS")
    call(t.record_failure_mode, ctx, functional_failure_id="FF-003",
         description="Transmisor de presión de succión con deriva sin señal de falla",
         mechanism="Falla de Instrumentación", iso_code="PDE",
         cause="Envejecimiento",
         root_cause="Deriva del sensor por ciclos térmicos",
         failure_pattern="Fin de Vida Útil",
         tpef_hours=26280, tpef_fuente="Opinión de experto")
    call(t.record_failure_mode, ctx, functional_failure_id="FF-001",
         description="Rotura del impulsor por golpe de ariete",
         mechanism="Falla Mecánica", iso_code="BRD",
         cause="Causa externa/ambiental",
         root_cause="No aplicable: el sistema tiene arrancadores suaves y válvulas "
                    "de cierre lento",
         failure_pattern="Aleatoria",
         credible=False,
         non_credible_discard="Descartado por no credibilidad: arrancador suave y "
                              "válvulas de cierre lento eliminan el golpe de ariete "
                              "en este contexto operativo")

    call(t.record_effect, ctx, failure_mode_id="FM-001",
         local="Ruido hidráulico, vibración creciente y erosión del impulsor",
         system="Caudal de transferencia cae por debajo de 850 GPM",
         plant="Parada no programada de la transferencia de crudo",
         is_hidden=False, operational=True)
    call(t.record_effect, ctx, failure_mode_id="FM-002",
         local="Goteo de crudo por el sello hacia el piso de la estación",
         system="Pérdida de contención del proceso",
         plant="Derrame con impacto ambiental y riesgo de incendio",
         is_hidden=False, safety=True, environment=True)
    call(t.record_effect, ctx, failure_mode_id="FM-003",
         local="Lectura de presión de succión congelada; sin alarma",
         system="Protección de disparo por baja succión indisponible",
         plant="Ante baja succión real, la bomba cavita hasta daño mayor del sello "
               "y el impulsor",
         is_hidden=True, safety=True)

    call(t.record_control, ctx, failure_mode_id="FM-001", kind="detectivo",
         description="Ronda operativa diaria con lectura de presión y caudal")
    call(t.record_control, ctx, failure_mode_id="FM-002", kind="preventivo",
         description="Procedimiento de arranque con verificación de venteo del sello")
    call(t.record_control, ctx, failure_mode_id="FM-003", kind="preventivo",
         description="Calibración anual de instrumentos de la estación")
    call(t.advance_phase, ctx)

    print("— P4: riesgo S/O/D (tablas SAE J1739)")
    call(t.score_risk, ctx, failure_mode_id="FM-001", severity=7, occurrence=6, detection=4)
    call(t.score_risk, ctx, failure_mode_id="FM-002", severity=9, occurrence=4, detection=3)
    call(t.score_risk, ctx, failure_mode_id="FM-003", severity=9, occurrence=3, detection=8)
    call(t.advance_phase, ctx)

    print("— P5: decisión RCM + confirmación humana (HITL)")
    call(t.run_decision_logic, ctx, failure_mode_id="FM-001",
         pf_interval_sufficient=True)
    # FM-002 tiene consecuencia Seguridad/Ambiente → primero exige confirmación humana
    call(t.run_decision_logic, ctx, failure_mode_id="FM-002",
         pf_interval_sufficient=True)
    call(t.run_decision_logic, ctx, failure_mode_id="FM-002",
         pf_interval_sufficient=True, approver="María Torres — Supervisora de Operaciones")
    call(t.run_decision_logic, ctx, failure_mode_id="FM-003",
         failure_finding_feasible=True)
    call(t.run_decision_logic, ctx, failure_mode_id="FM-003",
         failure_finding_feasible=True,
         approver="José Rivas — Líder de Instrumentación")
    call(t.calculate_ffi, ctx, method="single_single",
         mtive_hours=26280, mted_hours=8760, mmf_hours=175200)
    call(t.record_action, ctx, failure_mode_id="FM-001",
         what="Implementar monitoreo mensual de vibración y presión de succión con "
              "límites de alarma",
         who="Predictivo", when="Mensual",
         verification="Tendencia de vibración estable y caudal ≥ 850 GPM")
    call(t.record_action, ctx, failure_mode_id="FM-002",
         what="Inspección trimestral del sello mecánico y verificación del plan de "
              "arranque con venteo",
         who="Mecánico", when="Trimestral",
         verification="Sin goteo visible en piso; registro de arranques conformes")
    call(t.record_action, ctx, failure_mode_id="FM-003",
         what="Prueba funcional del lazo de disparo por baja presión de succión",
         who="Instrumentista", when="Semestral",
         verification="Disparo simulado exitoso registrado en el CMMS")
    call(t.score_risk, ctx, failure_mode_id="FM-001",
         severity=7, occurrence=3, detection=2, is_residual=True)
    call(t.advance_phase, ctx)

    print("— P6: plan de mantenimiento, KPIs y validación")
    call(t.record_task, ctx, failure_mode_id="FM-001",
         description="Análisis de vibraciones y verificación de presión de succión "
                     "en P-03070 (4 puntos, espectro y envolvente)",
         frequency="Mensual", duration_hours=2.0, discipline="Predictivo")
    call(t.record_task, ctx, failure_mode_id="FM-002",
         description="Inspección del sello mecánico y del plan de arranque con venteo",
         frequency="Trimestral", duration_hours=3.0, discipline="Mecánico")
    call(t.record_task, ctx, failure_mode_id="FM-003",
         description="Prueba funcional del lazo de disparo por baja presión de succión",
         frequency="Semestral", duration_hours=4.0, discipline="Instrumentista",
         requires_shutdown=True)
    call(t.record_governance, ctx,
         kpis="MTBF=> 8.760 h; Cumplimiento del plan=> 95%; Derrames=0",
         review_triggers="Falla grave o repetitiva; Cambio de condiciones operativas; "
                         "Incidente ambiental",
         validation_signoff="Validado por operaciones y mantenimiento — reunión de "
                            "cierre estación de flujo")
    call(t.advance_phase, ctx)

    print("— Export del entregable")
    out = call(t.export_excel, ctx)
    assert "definitivo" in out, out
    print("\n✅ DEMO SEMBRADA. Entregable en data/exports/demo/ (ver ruta arriba).")


if __name__ == "__main__":
    main()
