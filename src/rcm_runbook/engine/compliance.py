"""Phase gates and cross-entity invariants (JA1011 compliance).

All checks return Spanish deficiency messages — they surface directly to
stakeholders when `advance_phase` or `export_excel` refuses.
"""

from __future__ import annotations

from rcm_runbook.models.catalogs import FRECUENCIA_EN_HORAS, MaintenancePolicy
from rcm_runbook.models.domain import FunctionKind
from rcm_runbook.models.session import Phase, RCMSession

REDESIGN_FAMILY = {MaintenancePolicy.RD, MaintenancePolicy.EXED, MaintenancePolicy.CC}

MIN_TEAM_ROLES = 2


def check_gate(session: RCMSession, phase: Phase) -> list[str]:
    """Deficiencies blocking advancement OUT of `phase`. Empty list = gate green."""
    checks = {
        Phase.P1_ALCANCE: _gate_p1,
        Phase.P2_FUNCIONES: _gate_p2,
        Phase.P3_AMEF: _gate_p3,
        Phase.P4_RIESGO: _gate_p4,
        Phase.P5_DECISION: _gate_p5,
        Phase.P6_PLAN: _gate_p6,
    }
    check = checks.get(phase)
    return check(session) if check else []


def _credible_modes(session: RCMSession) -> list[str]:
    return [fmid for fmid, fm in session.failure_modes.items() if fm.credible]


def _gate_p1(s: RCMSession) -> list[str]:
    issues = []
    if not s.scope.equipment_description:
        issues.append("Falta la descripción del activo/equipo analizado.")
    if not s.scope.tag:
        issues.append("Falta el TAG o código técnico del activo.")
    if not s.scope.boundaries:
        issues.append("Faltan los límites físicos del análisis.")
    if not s.scope.objective:
        issues.append("Falta el objetivo del análisis.")
    if not s.scope.operating_context:
        issues.append("Falta el contexto operacional (régimen, carga, redundancia, ambiente).")
    if len(s.team) < MIN_TEAM_ROLES:
        issues.append(
            f"El equipo multidisciplinario requiere al menos {MIN_TEAM_ROLES} integrantes "
            "(mantenimiento y operaciones como mínimo)."
        )
    return issues


def _gate_p2(s: RCMSession) -> list[str]:
    issues = []
    primaries = [f for f in s.functions.values() if f.kind == FunctionKind.PRIMARIA]
    if not primaries:
        issues.append("Se requiere al menos una función primaria con estándar cuantitativo.")
    if not s.secondary_functions_confirmed:
        issues.append(
            "Falta preguntar explícitamente por funciones secundarias "
            "(contención, control, integridad) — registre las que existan o confirme 'ninguna'."
        )
    if not s.protective_functions_confirmed:
        issues.append(
            "Falta preguntar explícitamente por funciones/dispositivos de PROTECCIÓN "
            "(alarmas, disparos, válvulas de seguridad, respaldo) — ahí viven las fallas "
            "ocultas. Registre las que existan o confirme 'ninguna'."
        )
    functions_with_ff = {ff.function_id for ff in s.functional_failures.values()}
    for f in s.functions.values():
        if f.id not in functions_with_ff:
            issues.append(f"La función {f.id} ({f.verb} {f.object}) no tiene fallas funcionales.")
    return issues


def _gate_p3(s: RCMSession) -> list[str]:
    issues = []
    ff_with_modes = {fm.functional_failure_id for fm in s.failure_modes.values()}
    for ff in s.functional_failures.values():
        if ff.id not in ff_with_modes:
            issues.append(f"La falla funcional {ff.id} no tiene modos de falla.")
    for fmid in _credible_modes(s):
        fm = s.failure_modes[fmid]
        if fmid not in s.effects:
            issues.append(f"El modo {fmid} ({fm.description[:40]}) no tiene efectos registrados.")
        if fmid not in s.controls:
            issues.append(
                f"El modo {fmid} no tiene controles actuales registrados "
                "(registre los que existan o confirme 'ninguno')."
            )
    return issues


def _gate_p4(s: RCMSession) -> list[str]:
    issues = []
    for fmid in _credible_modes(s):
        if fmid not in s.risk_scores:
            issues.append(f"El modo {fmid} no tiene valoración S/O/D.")
    issues.extend(
        f"La valoración del modo {fmid} está desactualizada (cambiaron sus insumos) — re-evalúe."
        for fmid in s.stale_decisions()
        if fmid in s.risk_scores
    )
    return issues


def _gate_p5(s: RCMSession) -> list[str]:
    issues = []
    for fmid in _credible_modes(s):
        if fmid not in s.decisions:
            issues.append(f"El modo {fmid} no tiene decisión RCM (política de mantenimiento).")
            continue
        decision = s.decisions[fmid]
        effect = s.effects.get(fmid)
        se = bool(effect and (effect.safety or effect.environment))
        if se and not decision.hitl_confirmed_by:
            issues.append(
                f"El modo {fmid} tiene consecuencia seguridad/ambiente sin confirmación humana."
            )
        if decision.policy == MaintenancePolicy.OHF and se:
            issues.append(
                f"El modo {fmid}: operar hasta la falla no es admisible con consecuencia "
                "de seguridad/ambiente."
            )
        if fmid not in s.actions:
            issues.append(f"El modo {fmid} no tiene acciones recomendadas.")
        issues.extend(_residual_issues(s, fmid))
    issues.extend(
        f"La decisión del modo {fmid} está desactualizada (cambiaron sus insumos) — re-ejecute "
        "la lógica de decisión."
        for fmid in s.stale_decisions()
    )
    return issues


def _residual_issues(s: RCMSession, fmid: str) -> list[str]:
    """Residual-S invariance: S only drops with a redesign-family policy (Rd/ExEd/CC)."""
    initial = s.risk_scores.get(fmid)
    residual = s.residual_scores.get(fmid)
    if not initial or not residual:
        return []
    decision = s.decisions.get(fmid)
    if residual.severity < initial.severity and (
        not decision or decision.policy not in REDESIGN_FAMILY
    ):
        return [
            f"El modo {fmid}: la severidad residual ({residual.severity}) no puede ser menor "
            f"que la inicial ({initial.severity}) sin rediseño/cambio (Rd, ExEd o CC). "
            "La severidad solo cambia si se modifica el diseño o se reduce la consecuencia."
        ]
    return []


def _gate_p6(s: RCMSession) -> list[str]:
    issues = []
    for fmid, decision in s.decisions.items():
        if decision.policy == MaintenancePolicy.OHF:
            continue  # run-to-failure produces no scheduled task
        if not s.failure_modes[fmid].credible:
            continue
        if fmid not in s.tasks:
            issues.append(
                f"El modo {fmid} (política {decision.policy.value}) no tiene tarea de "
                "mantenimiento en el plan."
            )
    for fmid in s.tasks:
        fm = s.failure_modes.get(fmid)
        if fm and fm.tpef is None:
            issues.append(
                f"El modo {fmid} tiene tarea pero falta el TPEF con fuente de dato "
                "(OREDA / historial / opinión de experto)."
            )
    if not s.kpis:
        issues.append("Faltan los KPIs de seguimiento (MTBF, MTTR, disponibilidad...).")
    if not s.review_triggers:
        issues.append("Faltan los disparadores de revisión periódica del análisis.")
    if not s.validation_signoff:
        issues.append("Falta la validación/aprobación con operaciones y mantenimiento.")
    return issues


def export_blockers(session: RCMSession) -> list[str]:
    """All gates must be green (through P6) before the deliverable can be exported."""
    issues: list[str] = []
    for phase in (
        Phase.P1_ALCANCE,
        Phase.P2_FUNCIONES,
        Phase.P3_AMEF,
        Phase.P4_RIESGO,
        Phase.P5_DECISION,
        Phase.P6_PLAN,
    ):
        for issue in check_gate(session, phase):
            issues.append(f"[Fase {phase.value}] {issue}")
    issues.extend(tareas_contradictorias(session))
    issues.extend(tareas_mas_lentas_que_el_ffi(session))
    return issues


def tareas_mas_lentas_que_el_ffi(session: RCMSession) -> list[str]:
    """El FFI calculado tiene que gobernar la frecuencia que ejecuta el CMMS.

    El entregable salía con los dos números contradiciéndose y ningún aviso:
    AUDITORIA decía «FFI = 1752 h» para el presostato y el PLAN decía
    «Semestral» (4380 h). El ✔ del FFI era literalmente cierto —el número
    llegaba a una celda— y a la vez engañoso, porque no mandaba sobre la única
    columna que alguien ejecuta. Es un dispositivo de protección con
    consecuencia de seguridad: probarlo 2,5 veces menos seguido de lo calculado
    no es un detalle de formato.

    Solo se bloquea cuando la tarea es MÁS LENTA que el intervalo calculado.
    Probar más seguido de lo necesario es conservador y decisión del cliente.
    """
    problemas: list[str] = []
    for fmid, ffi in session.ffi_por_modo.items():
        for tarea in session.tasks.get(fmid, []):
            horas = FRECUENCIA_EN_HORAS.get(tarea.frequency)
            if horas is None:
                continue  # frecuencia sin equivalencia fiable (p. ej. 'Quinquenal')
            if horas > ffi.horas:
                problemas.append(
                    f"[Plan] La búsqueda de fallas de {fmid} está calculada cada "
                    f"{ffi.horas:.0f} h, pero la tarea '{tarea.description}' se "
                    f"ejecuta '{tarea.frequency}' ({horas:.0f} h) — más espaciada que "
                    "el intervalo calculado. Ajuste la frecuencia o recalcule el FFI."
                )
    return problemas


def tareas_contradictorias(session: RCMSession) -> list[str]:
    """Dos tareas del mismo modo que se contradicen bloquean el entregable.

    El guardián de casi-duplicados de `add_task` ataja las reformulaciones, pero
    no puede cazar un sinónimo («Medición de vibraciones» frente a «Análisis de
    vibración») sin una lista de sinónimos que rechazaría tareas legítimas. Esta
    es la red que sí es determinista: no adivina si son la misma tarea, solo se
    niega a entregar un plan donde dos filas del mismo modo mandan cosas
    distintas — que es lo que el cliente se lleva al CMMS.

    Se vio en el primer análisis completo real: «Mensual, 2 h, Mecánico, sin
    paro» y «Semestral, 3 h, Instrumentista, con paro» para el mismo modo, y la
    hoja AMEF mostró en silencio solo la primera.

    La primera versión de esto comparaba SOLO `requires_shutdown`, o sea una de
    las cuatro diferencias que narra el párrafo de arriba: ese incidente se
    cazaba por casualidad. Con un sinónimo y dos frecuencias distintas, el plan
    definitivo salía con dos periodicidades para el mismo trabajo y nada lo
    paraba. Ahora se comparan los cuatro campos que el CMMS ejecuta.
    """
    problemas: list[str] = []
    for fmid, tareas in session.tasks.items():
        if len(tareas) < 2:
            continue
        for i, a in enumerate(tareas):
            for b in tareas[i + 1 :]:
                if not RCMSession._casi_igual(a.description, b.description):
                    # Dos tareas de verdad distintas (termografía y análisis de
                    # aceite) pueden y deben tener frecuencias distintas.
                    continue
                choques = [
                    f"{etiqueta}: '{getattr(a, campo)}' contra '{getattr(b, campo)}'"
                    for campo, etiqueta in (
                        ("frequency", "frecuencia"),
                        ("duration_hours", "duración"),
                        ("discipline", "ejecutor"),
                        ("requires_shutdown", "requiere paro"),
                    )
                    if getattr(a, campo) != getattr(b, campo)
                ]
                if choques:
                    problemas.append(
                        f"[Plan] {fmid} tiene dos tareas equivalentes que se "
                        f"contradicen — '{a.description}' y '{b.description}' — en "
                        + "; ".join(choques)
                        + ". Al CMMS no se le puede mandar las dos: resuelva cuál "
                        "vale (record_task con reemplazar=True) antes de exportar."
                    )
    return problemas


def validate_ja1011(session: RCMSession) -> list[str]:
    """Audit-level JA1011 conformance warnings (non-blocking, logged)."""
    warnings: list[str] = []
    if not any(f.kind == FunctionKind.PROTECCION for f in session.functions.values()):
        warnings.append(
            "No se registraron funciones de protección — confirme que el activo "
            "realmente no tiene dispositivos de protección."
        )
    for fmid, decision in session.decisions.items():
        if len(decision.justification.strip()) < 15:
            warnings.append(f"La decisión del modo {fmid} tiene justificación insuficiente.")
    hidden_no_bf = [
        fmid
        for fmid, d in session.decisions.items()
        if (e := session.effects.get(fmid)) is not None
        and e.is_hidden
        and d.policy == MaintenancePolicy.OHF
        and (e.safety or e.environment)
    ]
    for fmid in hidden_no_bf:
        warnings.append(
            f"El modo oculto {fmid} con consecuencia SE quedó en OHF — no conforme JA1011."
        )
    return warnings
