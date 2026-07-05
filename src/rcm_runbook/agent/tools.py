"""Tool layer — thin @tool wrappers over the domain aggregate and engines.

Application-layer responsibilities live here: loading/saving RCMSession from
Agno session_state, gate orchestration before export, HITL ledger calls, and
translating every exception into an actionable Spanish message (never a
traceback). Domain math stays in engine/ — the LLM never computes it.
"""

from __future__ import annotations

import functools
import json
import logging
import time
from collections.abc import Callable
from typing import Any

from agno.tools.decorator import tool

from rcm_runbook.config import settings
from rcm_runbook.engine import compliance
from rcm_runbook.engine.decision_logic import (
    DecisionAnswers,
    HITLRequired,
    decide,
    decide_confirmed,
)
from rcm_runbook.engine.ffi import calculate_ffi as _calculate_ffi
from rcm_runbook.engine.scoring import anchor_es, summarize
from rcm_runbook.export.excel import export_xlsx
from rcm_runbook.knowledge.handbook import consult
from rcm_runbook.models.catalogs import fixture, iso_code_info, normalize_data_source
from rcm_runbook.models.domain import (
    FunctionKind,
    MaintenanceTask,
    RecommendedAction,
    RiskScore,
    TPEFEstimate,
)
from rcm_runbook.models.session import (
    PHASE_NAMES_ES,
    SCHEMA_VERSION,
    Phase,
    RCMSession,
    ScopeMeta,
    TeamMember,
)

logger = logging.getLogger("rcm_runbook.tools")

SESSION_KEY = "rcm"


def _load(run_context: Any) -> RCMSession:
    state = run_context.session_state
    if state is None:
        state = {}
        run_context.session_state = state
    raw = state.get(SESSION_KEY)
    if raw is None:
        session = RCMSession()
        state[SESSION_KEY] = session.model_dump(mode="json")
        return session
    stored_version = raw.get("schema_version", 0) if isinstance(raw, dict) else 0
    if stored_version > SCHEMA_VERSION:
        raise ValueError(
            f"La sesión guardada usa un esquema más nuevo (v{stored_version}) que esta "
            f"versión de la aplicación (v{SCHEMA_VERSION}). Actualice rcm-runbook antes "
            "de reanudar esta sesión."
        )
    return RCMSession.model_validate(raw)


def _save(run_context: Any, session: RCMSession) -> None:
    run_context.session_state[SESSION_KEY] = session.model_dump(mode="json")


def _spanish_errors(fn: Callable[..., str]) -> Callable[..., str]:
    """Surface any failure as an actionable Spanish message + structured log."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> str:
        start = time.monotonic()
        name = fn.__name__
        try:
            result = fn(*args, **kwargs)
            logger.info(
                json.dumps(
                    {
                        "tool": name,
                        "outcome": "ok",
                        "duration_ms": round((time.monotonic() - start) * 1000),
                    },
                    ensure_ascii=False,
                )
            )
            return result
        except HITLRequired as exc:
            logger.info(json.dumps({"tool": name, "outcome": "hitl_required"}))
            return (
                f"⚠ CONFIRMACIÓN HUMANA REQUERIDA: {exc.reason_es}\n"
                "Pida al responsable (p.ej. supervisor HSE) que confirme, y registre "
                "la decisión con run_decision_logic pasando approver='<nombre y cargo>'."
            )
        except Exception as exc:  # noqa: BLE001 — every tool failure surfaces in Spanish
            logger.warning(json.dumps({"tool": name, "outcome": "error", "error": str(exc)[:300]}))
            detail = str(exc)
            if "validation error" in detail.lower():
                # Pydantic messages already carry our Spanish validators; trim the noise
                detail = "\n".join(
                    line for line in detail.splitlines()
                    if line.strip() and not line.startswith(("For further", "    "))
                )
            return f"❌ No se pudo completar la operación: {detail}"

    return wrapper


# ---------------------------------------------------------------------------
# P1 — Alcance y contexto
# ---------------------------------------------------------------------------


@tool
@_spanish_errors
def record_scope(
    run_context: Any,
    equipment_family: str = "",
    equipment_description: str = "",
    tag: str = "",
    location: str = "",
    boundaries: str = "",
    interfaces: str = "",
    normal_conditions: str = "",
    objective: str = "",
    operating_context: str = "",
) -> str:
    """Registra o actualiza el alcance del análisis: activo, TAG, límites, contexto
    operacional y objetivo. Pase solo los campos que el interesado haya confirmado."""
    session = _load(run_context)
    current = session.scope.model_dump()
    updates = {k: v for k, v in locals().items() if k in current and v}
    current.update(updates)
    session.scope = ScopeMeta(**current)
    _save(run_context, session)
    missing = [k for k, v in session.scope.model_dump().items() if not v]
    note = f" Campos pendientes: {', '.join(missing)}." if missing else " Alcance completo."
    return f"✔ Alcance actualizado ({', '.join(updates)})." + note


@tool
@_spanish_errors
def record_team_member(run_context: Any, name: str, role: str) -> str:
    """Agrega un integrante al equipo multidisciplinario (nombre y rol/disciplina)."""
    session = _load(run_context)
    session.team.append(TeamMember(name=name, role=role))
    _save(run_context, session)
    return f"✔ Integrante registrado: {name} ({role}). Total: {len(session.team)}."


# ---------------------------------------------------------------------------
# P2 — Funciones y fallas funcionales
# ---------------------------------------------------------------------------


@tool
@_spanish_errors
def record_function(
    run_context: Any, kind: str, verb: str, object: str, performance_standard: str
) -> str:
    """Registra una función del activo. kind: 'primaria', 'secundaria' o 'proteccion'.
    El estándar de desempeño debe ser cuantitativo/verificable (ej. '120 m³/h a 6 bar')."""
    session = _load(run_context)
    fn = session.add_function(
        kind=FunctionKind(kind), verb=verb, object=object,
        performance_standard=performance_standard,
    )
    _save(run_context, session)
    return f"✔ Función {fn.id} registrada: {fn.statement}"


@tool
@_spanish_errors
def confirm_no_functions(run_context: Any, kind: str) -> str:
    """Registra la confirmación explícita de que NO existen funciones de un tipo.
    kind: 'secundaria' o 'proteccion'. Úselo solo tras preguntar al interesado."""
    session = _load(run_context)
    session.confirm_no_functions_of_kind(FunctionKind(kind))
    _save(run_context, session)
    return f"✔ Confirmado: el activo no tiene funciones de tipo '{kind}'."


@tool
@_spanish_errors
def record_functional_failure(run_context: Any, function_id: str, description: str) -> str:
    """Registra una falla funcional (forma en que se pierde una función registrada)."""
    session = _load(run_context)
    ff = session.add_functional_failure(function_id, description)
    _save(run_context, session)
    return f"✔ Falla funcional {ff.id} registrada para {function_id}: {description}"


# ---------------------------------------------------------------------------
# P3 — AMEF
# ---------------------------------------------------------------------------


@tool
@_spanish_errors
def record_failure_mode(
    run_context: Any,
    functional_failure_id: str,
    description: str,
    mechanism: str,
    iso_code: str,
    cause: str,
    root_cause: str,
    failure_pattern: str,
    credible: bool = True,
    non_credible_discard: str = "",
    pf_interval_hours: float | None = None,
    tpef_hours: float | None = None,
    tpef_fuente: str = "",
    tpef_note: str = "",
) -> str:
    """Registra un modo de falla con su código ISO 14224, causa (≠ modo), causa raíz,
    patrón de falla y — si se conocen — intervalo P-F y TPEF con su fuente de dato
    (OREDA / Historial CMMS / Opinión de experto / Fabricante). Si el modo NO es
    creíble en este contexto, pase credible=False con la justificación del descarte."""
    session = _load(run_context)
    tpef = None
    if tpef_hours:
        tpef = TPEFEstimate(
            value_hours=tpef_hours, fuente=normalize_data_source(tpef_fuente),
            note=tpef_note,
        )
    fm = session.add_failure_mode(
        functional_failure_id,
        description=description,
        mechanism=mechanism,
        iso_code=iso_code,
        cause=cause,
        root_cause=root_cause,
        failure_pattern=failure_pattern,
        credible=credible,
        non_credible_discard=non_credible_discard,
        pf_interval_hours=pf_interval_hours,
        tpef=tpef,
    )
    _save(run_context, session)
    if not credible:
        return f"✔ Modo {fm.id} registrado como NO creíble (descarte documentado en auditoría)."
    return f"✔ Modo de falla {fm.id} registrado: {description} [{iso_code}]"


@tool
@_spanish_errors
def record_effect(
    run_context: Any,
    failure_mode_id: str,
    local: str,
    system: str,
    plant: str,
    is_hidden: bool,
    safety: bool = False,
    environment: bool = False,
    operational: bool = False,
    non_operational: bool = False,
) -> str:
    """Registra los efectos de un modo de falla (local → sistema → planta) ASUMIENDO
    que NO se realiza mantenimiento, y marca las consecuencias (Seguridad, Ambiente,
    Operacional, No Operacional). is_hidden=True si el operador NO percibe la falla
    en condiciones normales (típico en dispositivos de protección)."""
    session = _load(run_context)
    session.set_effect(
        failure_mode_id,
        local=local, system=system, plant=plant, is_hidden=is_hidden,
        safety=safety, environment=environment,
        operational=operational, non_operational=non_operational,
    )
    _save(run_context, session)
    vis = "OCULTA" if is_hidden else "evidente"
    return f"✔ Efectos de {failure_mode_id} registrados (falla {vis})."


@tool
@_spanish_errors
def record_control(run_context: Any, failure_mode_id: str, kind: str, description: str) -> str:
    """Registra un control actual para un modo de falla.
    kind: 'preventivo', 'detectivo' o 'mitigante'."""
    session = _load(run_context)
    session.add_control(failure_mode_id, kind=kind, description=description)
    _save(run_context, session)
    return f"✔ Control {kind} registrado para {failure_mode_id}."


@tool
@_spanish_errors
def lookup_iso14224(run_context: Any, query: str = "") -> str:
    """Consulta el catálogo de códigos ISO 14224 de modos de falla (hoja MENU del
    cliente). Sin query lista todos; con query filtra por código o descripción."""
    fx = fixture()
    rows = []
    q = query.strip().upper()
    for c in fx.menu.iso14224_failure_mode_codes:
        if not q or q in c.code or q.lower() in c.definition.lower():
            rows.append(f"{c.code} — {c.definition}: {c.description}")
    return "\n".join(rows) if rows else f"Sin coincidencias para '{query}'."


# ---------------------------------------------------------------------------
# P4 — Riesgo
# ---------------------------------------------------------------------------


@tool
@_spanish_errors
def lookup_sod_table(run_context: Any, dimension: str, value: int = 0) -> str:
    """Consulta las tablas SAE J1739. dimension: 'severidad', 'ocurrencia' o 'deteccion'.
    Con value (1-10) devuelve el ancla exacta; sin value devuelve la tabla completa."""
    if value:
        return f"{dimension.capitalize()} {value}: {anchor_es(dimension, value)}"
    return "\n".join(f"{v}: {anchor_es(dimension, v)}" for v in range(10, 0, -1))


@tool
@_spanish_errors
def score_risk(
    run_context: Any,
    failure_mode_id: str,
    severity: int,
    occurrence: int,
    detection: int,
    is_residual: bool = False,
) -> str:
    """Registra la valoración S/O/D (1-10, tablas SAE J1739) de un modo de falla y
    calcula el RPN. is_residual=True para el riesgo residual tras las acciones."""
    session = _load(run_context)
    fm = session.failure_modes.get(failure_mode_id)
    if fm is not None and not is_residual and occurrence and fm.tpef is None:
        note = (
            "\nℹ Nota: la Ocurrencia debería justificarse con el TPEF y su fuente "
            "(OREDA/historial/experto) — regístrelo con record_failure_mode."
        )
    else:
        note = ""
    score = RiskScore(
        failure_mode_id=failure_mode_id,
        severity=severity, occurrence=occurrence, detection=detection,
        is_residual=is_residual,
        input_hash=session.current_snapshot(failure_mode_id)
        if failure_mode_id in session.failure_modes
        else "",
    )
    session.set_risk_score(score)
    _save(run_context, session)
    summary = summarize(score)
    caveats = ("\n⚠ " + "\n⚠ ".join(summary.caveats_es)) if summary.caveats_es else ""
    kind = "residual" if is_residual else "inicial"
    return (
        f"✔ Riesgo {kind} de {failure_mode_id}: {summary.sod} → RPN={summary.rpn} "
        f"(prioridad: {summary.priority_es}).{caveats}{note}"
    )


# ---------------------------------------------------------------------------
# P5 — Decisión RCM
# ---------------------------------------------------------------------------


@tool
@_spanish_errors
def run_decision_logic(
    run_context: Any,
    failure_mode_id: str,
    automated_monitoring_available: bool = False,
    pf_interval_sufficient: bool = False,
    aging_related: bool = False,
    restoration_feasible: bool = False,
    lubrication_related: bool = False,
    failure_finding_feasible: bool = False,
    redesign_identified: bool = False,
    consequences_tolerable: bool = False,
    approver: str = "",
) -> str:
    """Ejecuta la lógica de decisión RCM (determinística) para un modo de falla con
    las respuestas del equipo. Para consecuencias de Seguridad/Ambiente exige
    confirmación humana: vuelva a llamar con approver='<nombre y cargo>' tras obtenerla."""
    session = _load(run_context)
    fm = session.failure_modes.get(failure_mode_id)
    if fm is None:
        known = ", ".join(session.failure_modes) or "ninguno"
        return f"❌ No existe modo de falla '{failure_mode_id}'. Registrados: {known}."
    effect = session.effects.get(failure_mode_id)
    if effect is None:
        return f"❌ El modo {failure_mode_id} no tiene efectos registrados (record_effect primero)."
    answers = DecisionAnswers(
        automated_monitoring_available=automated_monitoring_available,
        pf_interval_sufficient=pf_interval_sufficient,
        aging_related=aging_related,
        restoration_feasible=restoration_feasible,
        lubrication_related=lubrication_related,
        failure_finding_feasible=failure_finding_feasible,
        redesign_identified=redesign_identified,
        consequences_tolerable=consequences_tolerable,
    )
    if approver:
        session.request_hitl(failure_mode_id, "Consecuencia de seguridad/ambiente")
        session.confirm_hitl(failure_mode_id, approver)
        decision = decide_confirmed(fm, effect, answers, approver=approver)
    else:
        try:
            decision = decide(fm, effect, answers)
        except HITLRequired as exc:
            session.request_hitl(failure_mode_id, exc.reason_es)
            _save(run_context, session)
            raise
    decision = decision.model_copy(
        update={"input_hash": session.current_snapshot(failure_mode_id)}
    )
    session.set_decision(decision)
    _save(run_context, session)
    route = decision.evident_route or decision.hidden_route or "—"
    prov = " (PROVISIONAL — confirmar con el cliente)" if decision.provisional else ""
    logger.info(json.dumps({
        "decision": failure_mode_id, "policy": decision.policy,
        "consequence": decision.consequence_class, "route": str(route),
        "hitl": decision.hitl_confirmed_by or "",
    }, ensure_ascii=False))
    return (
        f"✔ Decisión de {failure_mode_id}: {decision.policy.value}{prov} "
        f"(consecuencia: {decision.consequence_class.value}, ruta: {route}).\n"
        f"Justificación: {decision.justification}"
    )


@tool
@_spanish_errors
def calculate_ffi(
    run_context: Any,
    method: str,
    mtive_hours: float = 0,
    mted_hours: float = 0,
    mmf_hours: float = 0,
    u_fraction: float = 0,
    n_devices: int = 1,
    mted_list_hours: str = "",
    cff: float = 0,
    cmf: float = 0,
) -> str:
    """Calcula el intervalo de búsqueda de fallas (FFI) — SOLO para modos de falla
    ocultos de dispositivos de protección. method: 'availability', 'single_single',
    'multi_single', 'single_multi' o 'economic'. mted_list_hours: lista separada por
    comas para multi_single. La aceptación del Mmf con consecuencia de seguridad es
    una decisión humana."""
    params: dict[str, Any] = {}
    if method == "availability":
        params = {"u": u_fraction, "mtive": mtive_hours}
    elif method == "single_single":
        params = {"mtive": mtive_hours, "mted": mted_hours, "mmf": mmf_hours}
    elif method == "multi_single":
        mted_list = [float(x) for x in mted_list_hours.split(",") if x.strip()]
        params = {"mtive": mtive_hours, "mted_list": mted_list, "mmf": mmf_hours}
    elif method == "single_multi":
        params = {"mtive": mtive_hours, "mted": mted_hours, "mmf": mmf_hours, "n": n_devices}
    elif method == "economic":
        params = {"mtive": mtive_hours, "mted": mted_hours, "cff": cff, "cmf": cmf}
    result = _calculate_ffi(method, params)
    warn = ("\n⚠ " + "\n⚠ ".join(result.warnings)) if result.warnings else ""
    return (
        f"✔ FFI ({method}): {result.ffi_hours:.0f} h ≈ {result.ffi_months:.1f} meses "
        f"≈ {result.ffi_years:.2f} años. Fórmula: {result.formula}{warn}"
    )


@tool
@_spanish_errors
def record_action(
    run_context: Any,
    failure_mode_id: str,
    what: str,
    who: str,
    when: str,
    verification: str,
    resources: str = "",
) -> str:
    """Registra una acción recomendada: qué se hará, quién, cuándo, con qué recursos
    y cómo se verificará su eficacia."""
    session = _load(run_context)
    session.add_action(RecommendedAction(
        failure_mode_id=failure_mode_id, what=what, who=who, when=when,
        verification=verification, resources=resources,
    ))
    _save(run_context, session)
    return f"✔ Acción recomendada registrada para {failure_mode_id}."


# ---------------------------------------------------------------------------
# P6 — Plan
# ---------------------------------------------------------------------------


@tool
@_spanish_errors
def record_task(
    run_context: Any,
    failure_mode_id: str,
    description: str,
    frequency: str,
    duration_hours: float,
    discipline: str,
    requires_shutdown: bool = False,
) -> str:
    """Registra una tarea del plan de mantenimiento (para el CMMS): descripción,
    frecuencia (catálogo del cliente: Diario…Según sea el caso), duración en horas,
    ejecutor/disciplina y si requiere paro del equipo."""
    session = _load(run_context)
    session.add_task(MaintenanceTask(
        failure_mode_id=failure_mode_id, description=description, frequency=frequency,
        duration_hours=duration_hours, discipline=discipline,
        requires_shutdown=requires_shutdown,
    ))
    _save(run_context, session)
    return f"✔ Tarea registrada para {failure_mode_id}: {description[:50]} [{frequency}]"


@tool
@_spanish_errors
def record_governance(
    run_context: Any,
    kpis: str = "",
    review_triggers: str = "",
    validation_signoff: str = "",
) -> str:
    """Registra KPIs de seguimiento (separados por ';' con meta opcional 'nombre=meta'),
    disparadores de revisión periódica (separados por ';') y la validación/aprobación
    de operaciones y mantenimiento."""
    from rcm_runbook.models.session import KPI

    session = _load(run_context)
    added = []
    if kpis:
        for chunk in kpis.split(";"):
            chunk = chunk.strip()
            if not chunk:
                continue
            name, _, target = chunk.partition("=")
            session.kpis.append(KPI(name=name.strip(), target=target.strip()))
        added.append(f"{len(session.kpis)} KPIs")
    if review_triggers:
        session.review_triggers.extend(
            t.strip() for t in review_triggers.split(";") if t.strip()
        )
        added.append(f"{len(session.review_triggers)} disparadores de revisión")
    if validation_signoff:
        session.validation_signoff = validation_signoff
        added.append("validación registrada")
    _save(run_context, session)
    return "✔ Gobernanza actualizada: " + ", ".join(added or ["sin cambios"])


# ---------------------------------------------------------------------------
# Progress / phase / export
# ---------------------------------------------------------------------------


@tool
@_spanish_errors
def get_progress(run_context: Any) -> str:
    """Muestra el estado del análisis: fase actual, entidades registradas, pendientes
    de la fase y confirmaciones humanas pendientes."""
    session = _load(run_context)
    issues = compliance.check_gate(session, session.phase)
    pending = (
        "\n\nPendientes de esta fase:\n- " + "\n- ".join(issues)
        if issues
        else "\n\n✔ Fase completa — puede avanzar con advance_phase."
    )
    return session.digest_es() + pending


@tool
@_spanish_errors
def advance_phase(run_context: Any) -> str:
    """Avanza a la siguiente fase del análisis. Se rechaza (con la lista de faltantes
    en español) si la fase actual no cumple sus criterios."""
    session = _load(run_context)
    issues = compliance.check_gate(session, session.phase)
    if issues:
        return (
            f"❌ No se puede avanzar de la fase {session.phase.value} "
            f"({PHASE_NAMES_ES[session.phase]}). Faltantes:\n- " + "\n- ".join(issues)
        )
    if session.phase == Phase.COMPLETADO:
        return "El análisis ya está completado."
    session.phase = Phase(session.phase + 1)
    _save(run_context, session)
    return (
        f"✔ Avanzó a la fase {session.phase.value}: {PHASE_NAMES_ES[session.phase]}."
    )


@tool
@_spanish_errors
def export_excel(run_context: Any, draft: bool = False) -> str:
    """Exporta el entregable Excel (hojas AMEF, PLAN DE MANTENIMIENTO, SAE-J1739 y
    AUDITORIA RCM). Sin draft=True se rechaza si el análisis está incompleto."""
    session = _load(run_context)
    if not draft:
        blockers = compliance.export_blockers(session)
        if blockers:
            return (
                "❌ El análisis está incompleto — no se puede exportar el entregable "
                "definitivo (use draft=True para un borrador):\n- " + "\n- ".join(blockers[:12])
            )
    session_id = getattr(run_context, "session_id", "") or "session"
    path = export_xlsx(session, settings.exports_dir, session_id=session_id, draft=draft)
    audit = compliance.validate_ja1011(session)
    warn = ("\n⚠ Advertencias JA1011: " + "; ".join(audit)) if audit else ""
    kind = "BORRADOR" if draft else "definitivo"
    url = f"/exports/{path.parent.name}/{path.name}"
    return (
        f"✔ Entregable {kind} exportado: {path}\n"
        f"Descarga: {url}{warn}"
    )


@tool
@_spanish_errors
def consult_handbook(run_context: Any, query: str) -> str:
    """Consulta el manual RCM (rcm-handbook.com) y el método de 20 pasos del cliente.
    Útil para explicar conceptos (P-F, búsqueda de fallas, patrones) a los interesados."""
    return consult(query)


@tool
@_spanish_errors
def explain_iso_code(run_context: Any, code: str) -> str:
    """Explica un código ISO 14224 del catálogo del cliente (definición y descripción)."""
    definition, description = iso_code_info(code.upper())
    return f"{code.upper()} — {definition}: {description}"


ALL_TOOLS = [
    record_scope,
    record_team_member,
    record_function,
    confirm_no_functions,
    record_functional_failure,
    record_failure_mode,
    record_effect,
    record_control,
    lookup_iso14224,
    lookup_sod_table,
    score_risk,
    run_decision_logic,
    calculate_ffi,
    record_action,
    record_task,
    record_governance,
    get_progress,
    advance_phase,
    export_excel,
    consult_handbook,
    explain_iso_code,
]
