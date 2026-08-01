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
import re
import threading
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
from rcm_runbook.errors import ReglaDeNegocio
from rcm_runbook.export.excel import export_xlsx
from rcm_runbook.knowledge.handbook import consult
from rcm_runbook.models.catalogs import (
    POLICY_LABELS_ES,
    ROUTE_LABELS_ES,
    fixture,
    iso_code_info,
    normalize_data_source,
)
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
    FFIRegistro,
    Phase,
    RCMSession,
    ScopeMeta,
    TeamMember,
)

logger = logging.getLogger("rcm_runbook.tools")

SESSION_KEY = "rcm"

# Un candado por sesión, y toda la herramienta dentro.
#
# `_load` lee el estado, la herramienta muta una copia y `_save` reescribe el
# objeto entero. Cuando el modelo emite dos llamadas en el mismo turno y agno
# las ejecuta en paralelo, la segunda parte de la foto vieja y su `_save` borra
# lo que escribió la primera. Observado en producción: `score_risk` contestó
# «✔ Riesgo inicial de FM-002: S9-O3-D8 → RPN=216» y seis turnos después el
# entregable se bloqueó porque FM-002 no tenía valoración. Un dato de riesgo con
# S=9 desaparecido, con un ✔ delante.
#
# El candado va en `_spanish_errors`, que envuelve a TODAS las herramientas: es
# el único punto por el que pasan todas, así que no hay forma de añadir una
# herramienta nueva y olvidarse de protegerla.
_CANDADOS: dict[str, threading.Lock] = {}
_CANDADOS_LOCK = threading.Lock()


def _candado(run_context: Any) -> threading.Lock:
    sid = str(getattr(run_context, "session_id", "") or "sin-sesion")
    with _CANDADOS_LOCK:
        return _CANDADOS.setdefault(sid, threading.Lock())


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


def _avanzar_si_la_compuerta_esta_verde(session: RCMSession) -> list[str]:
    """Avanza de fase mientras la compuerta lo permita, y dice hasta dónde llegó.

    `advance_phase` existía y el modelo no la llamaba: 31 turnos en producción,
    con el interesado pidiéndolo cuatro veces, y la sesión terminó en fase 1. El
    agente narraba el cambio de fase y seguía, así que las compuertas P2–P5 no
    llegaban a ejecutarse nunca y una sesión reanudada arrancaba leyendo fase 1.

    No hay nada que decidir aquí: `check_gate` ya sabe si la fase está completa y
    `advance_phase` habría aceptado exactamente estos avances. Dejar la decisión
    en el modelo era darle una elección que no era suya.
    """
    avanzadas: list[str] = []
    while session.phase != Phase.COMPLETADO and not compliance.check_gate(
        session, session.phase
    ):
        session.phase = Phase(session.phase + 1)
        avanzadas.append(f"{session.phase.value} ({PHASE_NAMES_ES[session.phase]})")
    return avanzadas


def _save(run_context: Any, session: RCMSession) -> None:
    avanzadas = _avanzar_si_la_compuerta_esta_verde(session)
    if avanzadas:
        logger.info(json.dumps({"fase_avanzada_a": avanzadas[-1]}, ensure_ascii=False))
        _ULTIMO_AVANCE[str(getattr(run_context, "session_id", "") or "")] = avanzadas
    run_context.session_state[SESSION_KEY] = session.model_dump(mode="json")


# El aviso del avance viaja pegado a la salida de la herramienta que lo provocó:
# el agente tiene que enterarse de que la fase cambió, o seguirá hablando de la
# fase vieja y repreguntando lo que ya está cerrado.
_ULTIMO_AVANCE: dict[str, list[str]] = {}


def _nota_de_avance(run_context: Any) -> str:
    avanzadas = _ULTIMO_AVANCE.pop(str(getattr(run_context, "session_id", "") or ""), None)
    if not avanzadas:
        return ""
    # Sin el número cuando es COMPLETADO: solo hay 6 fases, y el arreglo de la
    # ronda 9 corrigió el digest —lo que lee el modelo— dejando intactos los dos
    # mensajes que lee la persona.
    ultima = avanzadas[-1]
    if ultima.startswith(f"{Phase.COMPLETADO.value} "):
        return "\n➜ Fase completa. El análisis queda COMPLETADO."
    return "\n➜ Fase completa. El análisis avanzó a la fase " + ultima + "."


_RANGOS_EN_ESPANOL = (
    (
        "u must be in the open interval (0, 1)",
        "La indisponibilidad objetivo debe estar entre 0 y 1, sin incluirlos",
    ),
    ("must be a number", "debe ser un número"),
    ("must be > 0", "debe ser mayor que cero"),
    ("n must be an integer", "El número de dispositivos debe ser un entero"),
    ("n must be >= 1", "El número de dispositivos debe ser 1 o más"),
)


def _aviso_en_espanol(aviso: str) -> str:
    """Traduce los avisos del motor de FFI, que son ingleses a propósito.

    El motor emite EXACTAMENTE dos (engine/ffi.py:_build_result). La primera
    versión de esto traducía uno y tenía una tercera rama —«not a hidden
    failure»— que no corresponde a ningún texto del motor: código muerto que
    disfrazaba el hueco. El que faltaba salía crudo al chat y a la celda F de
    AUDITORIA, en la misma hoja que el arreglo decía haber limpiado.
    """
    numeros = re.findall(r"[\d.]+", aviso)
    calculado = numeros[0] if numeros else "?"
    if "exceeds the protective device MTBF" in aviso:
        return (
            f"El FFI calculado ({calculado} h) supera el TPEF del propio dispositivo "
            "de protección: el intervalo no es fiable, revise los datos de entrada."
        )
    if "is shorter than 24 h" in aviso:
        return (
            f"El FFI calculado ({calculado} h) es de menos de 24 horas: una búsqueda "
            "de fallas tan frecuente no suele ser practicable. Considere rediseñar el "
            "dispositivo de protección."
        )
    return aviso


def _en_espanol(mensaje: str) -> str:
    """Traduce los rechazos de rango del motor, que es inglés a propósito."""
    for ingles, espanol in _RANGOS_EN_ESPANOL:
        if ingles not in mensaje:
            continue
        # El motor antepone el nombre del parámetro ("mtive must be > 0, got
        # -5.0"); sin él la frase queda coja y el agente no sabe qué corregir.
        sujeto = mensaje.split(ingles)[0].strip()
        recibido = mensaje.rsplit(" ", 1)[-1]
        return (
            f"{sujeto + ' ' if sujeto else ''}{espanol} (recibí: {recibido})."
            if sujeto
            else f"{espanol} (recibí: {recibido})."
        )
    return mensaje


# Los identificadores del motor son ingleses y no se traducen (los fija su
# propia suite); lo que faltaba era su significado al lado, que es lo que el
# modelo copiaba mal cuando no lo tenía.
METODOS_FFI: tuple[tuple[str, str], ...] = (
    ("availability", "una indisponibilidad objetivo dada (usa u_fraction)"),
    ("single_single", "UNA función protegida, UN dispositivo, sin redundancia"),
    ("multi_single", "VARIAS funciones protegidas, UN SOLO dispositivo"),
    ("single_multi", "UNA función protegida, VARIOS dispositivos redundantes"),
    ("economic", "equilibra costos; solo si la consecuencia es puramente económica"),
)


def _spanish_errors(fn: Callable[..., str]) -> Callable[..., str]:
    """Surface any failure as an actionable Spanish message + structured log."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> str:
        run_context = args[0] if args else kwargs.get("run_context")
        with _candado(run_context):
            return _ejecutar(fn, args, kwargs)

    return wrapper


def _ejecutar(fn: Callable[..., str], args: Any, kwargs: Any) -> str:
    """El cuerpo de la herramienta, ya con el candado de su sesión tomado."""
    start = time.monotonic()
    name = fn.__name__
    try:
        result = fn(*args, **kwargs)
        # La nota del avance se pega aquí y no en cada herramienta: si el agente
        # no se entera de que la fase cambió, sigue hablando de la vieja y
        # repregunta lo que ya está cerrado.
        result += _nota_de_avance(args[0] if args else kwargs.get("run_context"))
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
    except ReglaDeNegocio as exc:
        # El método diciendo que el dato no vale. No es una avería, y no
        # puede llevar el banner técnico: el agente lo lee como sistema roto
        # y se inventa la causa en vez de repreguntar.
        logger.info(json.dumps({"tool": name, "outcome": "regla_de_negocio"}))
        return f"❌ {exc}"
    except Exception as exc:  # noqa: BLE001 — every tool failure surfaces in Spanish
        logger.warning(json.dumps({"tool": name, "outcome": "error", "error": str(exc)[:300]}))
        detail = str(exc)
        if "validation error" in detail.lower():
            # Pydantic messages already carry our Spanish validators; trim the noise
            detail = "\n".join(
                line for line in detail.splitlines()
                if line.strip() and not line.startswith(("For further", "    "))
            )
            # Un dato que no pasa la validación es siempre una llamada mal
            # armada, nunca una avería: el catálogo va en el propio mensaje,
            # así que decirle «avise a quien opera el sistema» lo manda a
            # buscar donde no es en lugar de corregir y reintentar.
            return f"❌ El dato no es válido, corrija y reintente:\n{detail}"
        return f"❌ No se pudo completar la operación: {detail}"


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
    run_context: Any, kind: str, verb: str, object: str, performance_standard: str,
    reemplazar: bool = False,
) -> str:
    """Registra una función del activo. kind: 'primaria', 'secundaria' o 'proteccion'.
    El estándar de desempeño debe ser cuantitativo/verificable (ej. '120 m³/h a 6 bar').

    reemplazar=True para CORREGIR una función ya registrada: mismo verbo y objeto,
    estándar nuevo. Sin él, la herramienta rechaza el cambio en vez de aplicarlo,
    para no pisar un dato bueno por un reintento."""
    session = _load(run_context)
    fn = session.add_function(
        kind=FunctionKind(kind), verb=verb, object=object,
        performance_standard=performance_standard, reemplazar=reemplazar,
    )
    _save(run_context, session)
    return f"✔ Función {fn.id} registrada: {fn.statement}"


@tool
@_spanish_errors
def confirm_no_functions(run_context: Any, kind: str) -> str:
    """Registra la confirmación explícita de que NO existen funciones de un tipo.
    kind: 'secundaria' o 'proteccion'. Úselo solo tras preguntar al interesado."""
    session = _load(run_context)
    try:
        tipo = FunctionKind(kind)
    except ValueError as exc:
        raise ReglaDeNegocio(
            f"Tipo de función desconocido: '{kind}'. Válidos: "
            + ", ".join(k.value for k in FunctionKind)
            + "."
        ) from exc
    session.confirm_no_functions_of_kind(tipo)
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
    credible: bool | None = None,
    non_credible_discard: str | None = None,
    pf_interval_hours: float | None = None,
    tpef_hours: float | None = None,
    tpef_fuente: str = "",
    tpef_note: str = "",
    reemplazar: bool = False,
) -> str:
    """Registra un modo de falla con su código ISO 14224, causa (≠ modo), causa raíz,
    patrón de falla y — si se conocen — intervalo P-F y TPEF con su fuente de dato
    (OREDA / Historial CMMS / Opinión de experto / Fabricante). Si el modo NO es
    creíble en este contexto, pase credible=False con la justificación del descarte.

    failure_pattern, EXACTAMENTE uno de estos cuatro: 'Mortalidad Infantil',
    'Aleatoria', 'Fin de Vida Útil', 'Aleatoria/Fin de Vida Útil'. No existen
    'Desgaste' ni 'Fatiga' — estaban en esta lista por error y el agente llegó a
    ofrecérselos al interesado dos veces en producción, para que la herramienta
    los rechazara después.

    reemplazar=True para CORREGIR un modo ya registrado: misma descripción, datos
    nuevos. Sin él la herramienta rechaza el cambio en vez de aplicarlo, para no
    pisar un dato bueno con un reintento."""
    session = _load(run_context)
    # Solo se manda lo que el agente mencionó. Antes se mandaban siempre los
    # diez campos, así que al corregir con reemplazar=True los que él no
    # repetía llegaban con su valor por defecto y borraban lo que había: se
    # corrigió una causa y se perdió el TPEF con fuente OREDA, y un descarte
    # documentado por no credibilidad se resucitó con la justificación vacía.
    campos: dict[str, Any] = {
        "description": description,
        "mechanism": mechanism,
        "iso_code": iso_code,
        "cause": cause,
        "root_cause": root_cause,
        "failure_pattern": failure_pattern,
    }
    if credible is not None:
        campos["credible"] = credible
    if non_credible_discard is not None:
        campos["non_credible_discard"] = non_credible_discard
    if pf_interval_hours is not None:
        campos["pf_interval_hours"] = pf_interval_hours
    if tpef_hours:
        campos["tpef"] = TPEFEstimate(
            value_hours=tpef_hours, fuente=normalize_data_source(tpef_fuente),
            note=tpef_note,
        )
    fm = session.add_failure_mode(
        functional_failure_id, reemplazar=reemplazar, **campos
    )
    _save(run_context, session)
    # Sobre el modo guardado, no sobre el parámetro: con  (no lo
    # mencionó) el mensaje anunciaba un descarte que nadie pidió.
    if not fm.credible:
        return f"✔ Modo {fm.id} registrado como NO creíble (descarte documentado en auditoría)."
    return f"✔ Modo de falla {fm.id} registrado: {fm.description} [{fm.iso_code}]"


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
    try:
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
    except ValueError as exc:
        # «No hay política determinable con las respuestas dadas…» es el motor
        # diciendo qué falta preguntarle al equipo, en español y accionable. Con
        # el banner técnico delante, el agente lo leía como avería y se paraba.
        raise ReglaDeNegocio(str(exc)) from exc
    decision = decision.model_copy(
        update={"input_hash": session.current_snapshot(failure_mode_id)}
    )
    session.set_decision(decision)
    _save(run_context, session)
    letra = decision.evident_route or decision.hidden_route or ""
    # Con su significado, como la política y como los métodos de FFI: es la
    # quinta vez que una sigla pelada acaba inventada.
    route = f"{letra} ({ROUTE_LABELS_ES[letra]})" if letra in ROUTE_LABELS_ES else "—"
    prov = " (PROVISIONAL — confirmar con el cliente)" if decision.provisional else ""
    logger.info(json.dumps({
        "decision": failure_mode_id, "policy": decision.policy,
        "consequence": decision.consequence_class, "route": str(route),
        "hitl": decision.hitl_confirmed_by or "",
    }, ensure_ascii=False))
    # Con el nombre al lado del acrónimo. POLICY_LABELS_ES llevaba escrito desde
    # el principio y sin cablear, y mientras tanto la herramienta devolvía 'Rd'
    # pelado: exactamente el hueco que el modelo rellena inventando («Rd» leído
    # como «reducción», «BF» como «by-pass funcional»). Es la misma causa que ya
    # estropeó los códigos ISO y los métodos de FFI.
    nombre = POLICY_LABELS_ES.get(decision.policy, "")
    politica = f"{decision.policy.value} ({nombre})" if nombre else decision.policy.value
    return (
        f"✔ Decisión de {failure_mode_id}: {politica}{prov} "
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
    failure_mode_id: str = "",
) -> str:
    """Calcula el intervalo de búsqueda de fallas (FFI) — SOLO para modos de falla
    ocultos de dispositivos de protección.

    Cada método y cada parámetro va con su definición: una sigla sin definir es un
    hueco que se rellena inventando, y aquí lo inventado acaba fijando cada cuánto
    se prueba un dispositivo de seguridad. Medido: cuatro corridas dieron cuatro
    significados distintos de 'multi_single', 'cff' y 'mted', ninguno correcto.

    method (usa EXACTAMENTE uno de estos identificadores):
    - 'availability' — una indisponibilidad objetivo dada. Usa u_fraction y
      mtive_hours. NO usa cff ni cmf.
    - 'single_single' — UNA función protegida, UN dispositivo, sin redundancia.
      Usa mtive_hours, mted_hours, mmf_hours.
    - 'multi_single' — VARIAS funciones protegidas, UN SOLO dispositivo (p. ej. un
      supresor de sobretensión que protege varios equipos). Usa mted_list_hours.
    - 'single_multi' — UNA función protegida, VARIOS dispositivos redundantes.
      Usa n_devices.
    - 'economic' — equilibra costos. SOLO si la falla múltiple tiene consecuencia
      puramente económica: seguridad y ambiente no se negocian por costo.

    Parámetros (todos en horas salvo donde se indique):
    - mtive_hours — TPEF del DISPOSITIVO DE PROTECCIÓN (cada cuánto falla él).
      No es la duración de la prueba.
    - mted_hours — TPEF de la FUNCIÓN PROTEGIDA (cada cuánto se le demanda).
    - mted_list_hours — los TPEF de cada función protegida, separados por comas,
      para 'multi_single'.
    - mmf_hours — TPEF tolerado de la FALLA MÚLTIPLE (cada cuánto se acepta que
      coincidan). Con consecuencia de seguridad, aceptarlo es decisión humana.
    - u_fraction — indisponibilidad objetivo, fracción entre 0 y 1 (0.02 = 2%).
    - n_devices — cuántos dispositivos redundantes hay.
    - cff — COSTO en dinero de ejecutar una búsqueda de falla. No es un
      coeficiente ni una fracción.
    - cmf — COSTO en dinero de la falla múltiple. No es un coeficiente.
    """
    if method not in dict(METODOS_FFI):
        # El motor rechaza en inglés («Unknown FFI method»); quien conversa en
        # español escribe 'disponibilidad' y recibía un fallo técnico ajeno.
        raise ReglaDeNegocio(
            f"Método de FFI desconocido: '{method}'. Los válidos, con lo que "
            "significa cada uno:\n" + "\n".join(f"- {m} — {d}" for m, d in METODOS_FFI)
        )
    params: dict[str, Any] = {}
    if method == "availability":
        params = {"u": u_fraction, "mtive": mtive_hours}
    elif method == "single_single":
        params = {"mtive": mtive_hours, "mted": mted_hours, "mmf": mmf_hours}
    elif method == "multi_single":
        try:
            mted_list = [float(x) for x in mted_list_hours.split(",") if x.strip()]
        except ValueError as exc:
            raise ReglaDeNegocio(
                f"mted_list_hours debe ser una lista de números separados por comas, "
                f"en horas. Recibí: '{mted_list_hours}'."
            ) from exc
        params = {"mtive": mtive_hours, "mted_list": mted_list, "mmf": mmf_hours}
    elif method == "single_multi":
        params = {"mtive": mtive_hours, "mted": mted_hours, "mmf": mmf_hours, "n": n_devices}
    elif method == "economic":
        params = {"mtive": mtive_hours, "mted": mted_hours, "cff": cff, "cmf": cmf}
    try:
        result = _calculate_ffi(method, params)
    except ValueError as exc:
        # El motor valida rangos y lo dice en inglés. Es una regla del método
        # (una indisponibilidad de 0 no tiene intervalo), no una avería.
        # El motor habla inglés a propósito (es dominio puro y sus tests lo
        # fijan). La traducción vive aquí, en la frontera con el agente, que es
        # quien conversa en español.
        raise ReglaDeNegocio(
            f"Los datos no permiten calcular el FFI con el método '{method}'. "
            + _en_espanol(str(exc))
        ) from exc
    # Los avisos del motor también vienen en inglés, y salían tal cual al chat y
    # a la hoja del entregable: `_en_espanol` envolvía excepciones, no
    # resultados. «Computed FFI (200000.0 h) exceeds the protective device MTBF»
    # en una conversación en español, y en la columna F de AUDITORIA.
    avisos = [_aviso_en_espanol(a) for a in result.warnings]
    warn = ("\n⚠ " + "\n⚠ ".join(avisos)) if avisos else ""
    guardado = ""
    if failure_mode_id:
        session = _load(run_context)
        if failure_mode_id not in session.failure_modes:
            known = ", ".join(session.failure_modes) or "ninguno"
            raise ReglaDeNegocio(
                f"No existe modo de falla '{failure_mode_id}'. Registrados: {known}."
            )
        session.ffi_por_modo[failure_mode_id] = FFIRegistro(
            horas=result.ffi_hours, metodo=method, formula=result.formula,
            avisos=avisos,
        )
        _save(run_context, session)
        guardado = f" Queda registrado para {failure_mode_id} y sale en el entregable."
    else:
        # Sin modo al que atarlo, el número se enseña y se pierde: no aparecía en
        # ninguna celda de ninguna hoja, y al CMMS llegaba la frecuencia que el
        # agente tecleaba a mano, sin relación con lo calculado.
        guardado = (
            " ⚠ NO queda registrado: vuelve a llamar con failure_mode_id=<FM-00X> "
            "para que este intervalo llegue al entregable."
        )
    return (
        f"✔ FFI ({method}): {result.ffi_hours:.0f} h ≈ {result.ffi_months:.1f} meses "
        f"≈ {result.ffi_years:.2f} años. Fórmula: {result.formula}{warn}{guardado}"
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
    reemplazar: bool = False,
) -> str:
    """Registra una tarea del plan de mantenimiento (para el CMMS).

    frequency, del catálogo del cliente, EXACTAMENTE como se escribe aquí:
    Diario, Semanal, Catorcenal, Quinquenal, Mensual, Bimestral, Trimestral,
    Tetramestral, Semestral, Anual, Bi-Anual, Tri-Anual, Tetra-Anual,
    Quinque-Annual, Parada de Planta, Arranque, Según sea el caso.

    **'Quinquenal' es ambiguo y NO debes elegirlo por tu cuenta.** En el catálogo
    aparece entre 'Catorcenal' y 'Mensual', que por posición sería quincenal (15
    días), pero la palabra sugiere cinco años — y 'Quinque-Annual' ya ocupa esa
    ranura al final de la serie anual. Si el intervalo que necesitas cae por ahí,
    pregunta al interesado qué significa en SU catálogo antes de registrarlo.
    discipline: Mecánico, Electricista, Rotativo, Predictivo, Estatico, Operador,
    Instrumentista. (Elidirlos con «…» hacía que el modelo inventara valores como
    'Diaria' o 'Cada 36 meses', y cada invento cuesta un turno de rechazo.)

    reemplazar=True para CORREGIR una tarea ya registrada: misma descripción o casi,
    datos nuevos. Sin él la herramienta rechaza el cambio en vez de aplicarlo."""
    session = _load(run_context)
    session.add_task(MaintenanceTask(
        failure_mode_id=failure_mode_id, description=description, frequency=frequency,
        duration_hours=duration_hours, discipline=discipline,
        requires_shutdown=requires_shutdown,
    ), reemplazar=reemplazar)
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
    # El aviso viaja en la salida, no solo en el system prompt: el modelo decide
    # la compuerta justo aquí, leyendo estos pendientes, y el prompt le queda
    # lejos. Reforzar la instrucción bajó los rechazos inventados de 3/3 a 2/3;
    # lo que faltaba era decírselo en el punto donde se equivoca.
    aviso = (
        "\n\n(Estos pendientes son SOLO de la fase actual. NO son los "
        "bloqueadores del entregable: esos los calcula export_excel y suelen "
        "ser más. Si el interesado pidió el Excel definitivo, llama a "
        "export_excel — no contestes con esta lista.)"
    )
    return session.digest_es() + pending + aviso


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
    if session.phase == Phase.COMPLETADO:
        return "✔ El análisis queda COMPLETADO: las seis fases están cerradas."
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
    # Enlace SIN la llave: la página de demo intercepta los enlaces /exports/ y
    # los descarga con la llave en la cabecera, igual que el botón. Antes se
    # incrustaba aquí, y eso (a) la dejaba en la transcripción guardada en
    # Postgres y en el historial del navegador, y (b) hacía que el modelo
    # evitara repetir el enlace, dejando al cliente sin nada que pulsar.
    url = f"/exports/{path.parent.name}/{path.name}"
    return (
        f"✔ Entregable {kind} exportado ({path.name}).\n"
        f"Entregue este enlace al interesado, tal cual: [Descargar el Excel]({url})"
        f"{warn}"
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
    from rcm_runbook.models.catalogs import fixture

    try:
        definition, description = iso_code_info(code.upper())
    except KeyError:
        # Un código ausente es un caso de negocio, no un fallo del sistema. Si se
        # deja escapar la excepción, _spanish_errors lo disfraza de "❌ No se pudo
        # completar la operación", el agente lo lee como avería y se inventa una
        # causa. La confusión nace aquí, no en el modelo.
        # Con la definición al lado, no solo el código: una lista pelada de
        # siglas es un hueco que el modelo rellena inventando. Medido — con
        # solo los códigos se inventó el significado de FTS, STP, HIO, LOO y
        # BRD, distinto en cada corrida, en un análisis de seguridad.
        disponibles = "\n".join(
            f"- {c.code} — {c.definition}"
            for c in fixture().menu.iso14224_failure_mode_codes
        )
        return (
            f"El código '{code.upper()}' no está en el catálogo ISO 14224 de este "
            f"cliente. Códigos disponibles:\n{disponibles}"
        )
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
