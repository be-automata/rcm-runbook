"""Phase gates and cross-entity invariants (JA1011 compliance).

All checks return Spanish deficiency messages — they surface directly to
stakeholders when `advance_phase` or `export_excel` refuses.
"""

from __future__ import annotations

from rcm_runbook.models.catalogs import FRECUENCIA_EN_HORAS, MaintenancePolicy
from rcm_runbook.models.domain import FunctionKind, sin_acentos
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
        for fmid in s.stale_scores()
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


#: Marcadores de posición vistos en el libro mayor real. Una firma que no nombra a
#: nadie no es una confirmación humana: es un campo relleno. La hoja AUDITORIA del
#: entregable afirma que alguien avaló la decisión, y debe poder respaldarlo.
_FIRMAS_GENERICAS = {
    "integrante confirmante", "confirmante", "operaciones", "mantenimiento",
    "el equipo", "equipo", "responsable", "supervisor", "n/a", "na", "pendiente",
    "usuario", "humano", "aprobador", "approver",
}


def firma_es_identificable(firma: str) -> bool:
    """¿La firma nombra a una persona concreta?

    Criterio: al menos dos palabras (nombre y apellido) y que no sea uno de los
    marcadores genéricos conocidos. Es deliberadamente laxo — busca atajar el
    relleno, no validar identidades.
    """
    limpia = sin_acentos(firma).lower().strip()
    if not limpia or limpia in _FIRMAS_GENERICAS:
        return False
    palabras = [p for p in limpia.replace(",", " ").split() if len(p) > 1]
    return len(palabras) >= 2



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


def bloqueadores_de_incoherencia(session: RCMSession) -> list[str]:
    """El subconjunto de `export_blockers` que denuncia contradicciones, no faltantes.

    Los bloqueadores son dos poblaciones distintas y conviene no confundirlas:

    - **Incompletitud** — falta contenido. "El modo FM-019 no tiene acciones
      recomendadas." Dice que la sesión no terminó.
    - **Incoherencia** — el contenido que SÍ existe se contradice. "La búsqueda de
      fallas de FM-014 está calculada cada 526 h, pero su tarea se ejecuta
      'Mensual' (730 h)." Dice que lo que se hizo está mal.

    La distinción importa porque admiten juicios opuestos: una sesión a medias es
    una sesión a medias, pero un plan que se contradice a sí mismo es un defecto
    aunque esté completo. Un dispositivo de protección que se prueba más espaciado
    que su propio intervalo calculado no es "otro camino igualmente válido".

    Es siempre un SUBCONJUNTO de `export_blockers`, y lo es por construcción: se
    parte de lo que la compuerta emitió y se seleccionan los que vienen de un
    generador de incoherencias. Nunca se reconstruye el criterio de la compuerta.

    La primera versión sí lo reconstruía —recorría los modos llamando a
    `_residual_issues`— y divergía en dos condiciones que `_gate_p5` aplica y esta
    función ignoraba: la compuerta sólo mira modos CREÍBLES, y hace `continue`
    antes de llegar al residual cuando el modo aún no tiene decisión. El resultado
    eran incoherencias que no existían como bloqueadores, con dos daños: rompían la
    partición en la que se apoya `bloqueadores_por_clase` y podían poner en rojo el
    criterio obligatorio `cero_incoherencias` del eval por algo que no bloqueaba
    nada. Filtrar en vez de reconstruir hace imposible esa clase de deriva.
    """
    de_plan = set(tareas_contradictorias(session)) | set(tareas_mas_lentas_que_el_ffi(session))
    residuales = {
        f"[Fase {Phase.P5_DECISION.value}] {issue}"
        for fmid in session.failure_modes
        for issue in _residual_issues(session, fmid)
    }
    delatores = de_plan | residuales
    # Se conserva el orden de export_blockers: es el que ve quien lee el informe.
    return [b for b in export_blockers(session) if b in delatores]


def bloqueadores_por_clase(session: RCMSession) -> dict[str, list[str]]:
    """`export_blockers` partido en {'incoherencia': [...], 'incompletitud': [...]}."""
    todos = export_blockers(session)
    incoherencia = bloqueadores_de_incoherencia(session)
    vistos = set(incoherencia)
    return {
        "incoherencia": incoherencia,
        "incompletitud": [b for b in todos if b not in vistos],
    }


def sigue_necesitando_busqueda_de_fallas(session: RCMSession, fmid: str) -> bool:
    """¿Este modo sigue requiriendo una tarea de búsqueda de fallas?

    Público a propósito: el entregable filtra con el MISMO criterio, para que no
    haya dos reglas que puedan divergir.

    El FFI se calcula para modos ocultos de dispositivos de protección. Si
    después el efecto se corrige y deja de ser oculto, si la política pasa a
    operar-hasta-la-falla, o si el modo se descarta por no creíble, el intervalo
    guardado ya no gobierna nada — y exigir una tarea para él es rechazar un
    análisis correcto.
    """
    fm = session.failure_modes.get(fmid)
    if fm is None or not fm.credible:
        return False
    decision = session.decisions.get(fmid)
    if decision is not None:
        if decision.policy == MaintenancePolicy.OHF:
            return False
        if decision.policy == MaintenancePolicy.BF:
            # La política ES búsqueda de fallas: hace falta la tarea aunque el
            # efecto diga que el modo no es oculto. Esa contradicción es del
            # análisis —la marca `stale_decisions` por su cuenta— y no una razón
            # para saltarse una compuerta de seguridad. Las excepciones se
            # añadieron para no rechazar análisis correctos, y este no lo es.
            return True
    efecto = session.effects.get(fmid)
    return efecto is None or efecto.is_hidden


def tareas_mas_lentas_que_el_ffi(session: RCMSession) -> list[str]:
    """La tarea de búsqueda de fallas tiene que ejecutar el intervalo calculado.

    Tres intentos, y los dos primeros estaban mal por lados opuestos:

    - Comparar TODAS las tareas rechazaba planes correctos: una calibración
      anual disparaba el bloqueo llamándose a sí misma «búsqueda de fallas».
    - Comparar «que cumpla ALGUNA» dejaba pasar la prueba funcional atrasada en
      cuanto hubiera cualquier otra tarea más frecuente al lado. Medido: prueba
      a `Parada de Planta` + una limpieza mensual cruzaba la compuerta con ✔.
      Ese es el defecto original, reabierto por su propio arreglo.

    El error estaba en intentar deducirlo: el modelo no tenía el dato. Ahora
    `MaintenanceTask.es_busqueda_de_fallas` lo dice, y esto solo mira esa fila.
    Falla cerrado: un modo con FFI y ninguna tarea marcada bloquea, porque no
    poder comprobarlo no es lo mismo que estar bien.
    """
    problemas: list[str] = []
    for fmid, ffi in session.ffi_por_modo.items():
        if not sigue_necesitando_busqueda_de_fallas(session, fmid):
            # Un FFI que dejó de tener sentido no puede bloquear para siempre.
            # Nada quita entradas de `ffi_por_modo`: se intentó borrarlas al
            # corregir el efecto y eso dejaba a esta compuerta sin nada que
            # visitar, apagando la excepción de política BF. Si el modo deja de
            # ser oculto, pasa a OHF o se descarta por no creíble, el intervalo
            # viejo bloqueaba el entregable sin salida. Y peor: `_gate_p6`
            # salta esos mismos modos a propósito, o sea que export_blockers se
            # contradecía consigo mismo.
            continue
        tareas = session.tasks.get(fmid, [])
        marcadas = [t for t in tareas if t.es_busqueda_de_fallas]
        if not marcadas:
            # El `continue` de la versión anterior daba por hecho que la
            # compuerta de la fase 6 ya exigía tareas. No es cierto: _gate_p6
            # salta los modos con política OHF y los no creíbles, así que un
            # modo con FFI y sin ninguna tarea exportaba limpio.
            otras = ", ".join(f"'{t.description}'" for t in tareas) or "ninguna"
            problemas.append(
                f"[Plan] {fmid} tiene un intervalo de búsqueda de fallas calculado "
                f"({ffi.horas:.0f} h) y ninguna tarea marcada como la que lo ejecuta. "
                f"Tareas registradas: {otras}. Registre la prueba con "
                "record_task(es_busqueda_de_fallas=True), o el intervalo calculado no "
                "gobierna nada."
            )
            continue
        for tarea in marcadas:
            horas = FRECUENCIA_EN_HORAS.get(tarea.frequency)
            if horas is None:
                problemas.append(
                    f"[Plan] La búsqueda de fallas de {fmid} está calculada cada "
                    f"{ffi.horas:.0f} h, pero su tarea '{tarea.description}' se ejecuta "
                    f"'{tarea.frequency}', que no tiene equivalencia en horas: no se "
                    "puede comprobar que se cumpla. Use una frecuencia del catálogo "
                    "con periodo definido."
                )
            elif horas > ffi.horas:
                problemas.append(
                    f"[Plan] La búsqueda de fallas de {fmid} está calculada cada "
                    f"{ffi.horas:.0f} h, pero su tarea '{tarea.description}' se ejecuta "
                    f"'{tarea.frequency}' ({horas:.0f} h) — más espaciada que el "
                    "intervalo calculado. Ajuste la frecuencia o recalcule el FFI."
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
