"""Export read-models — the export context owns the client's Excel dialect.

`AMEFRow`/`PlanRow` field order == benchmark column order (frozen fixture);
a golden test enforces the alias↔header match, so the domain model and the
deliverable can never drift independently. Row grain: one row per credible
failure mode (matching the benchmark; non-credible modes appear only in the
audit sheet with their documented discard).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from rcm_runbook.engine.decision_logic import derive_route
from rcm_runbook.models.catalogs import (
    POLICY_PLAN_COLUMN,
    ConsequenceClass,
    MaintenancePolicy,
)
from rcm_runbook.models.domain import DecisionResult, Effect, MaintenanceTask
from rcm_runbook.models.session import RCMSession

X = "X"  # benchmark marks consequence/strategy flags with X

# Un modo sin ruta decidida NO deja la celda muda: el interesado leyó 28 de 60
# filas en blanco y no tenía forma de saber si era un olvido del método o un
# defecto del exportador. Tampoco se inventa la letra: A/B/C/D y A/E/F/G
# dependen de la política elegida (`derive_route`), y escribir «B» donde podría
# ser «D» afirma en el entregable que el equipo descartó operar-hasta-la-falla.
SIN_DECISION = "PENDIENTE — sin decisión RCM"
RUTA_INCONSISTENTE = "PENDIENTE — ruta no reproducible"
# Distinto de SIN_DECISION: acá la decisión existe —la fila muestra su política,
# su tarea y su ejecutor— y lo que falta es la ruta. Decir «sin decisión RCM» en
# esa fila se contradice con sus propias columnas.
DECISION_SIN_RUTA = "PENDIENTE — decisión sin ruta registrada"


class AMEFRow(BaseModel):
    """One AMEF sheet row. Aliases are the exact benchmark headers (sic spellings)."""

    familia: str = Field(alias="Familia del Equipo")
    descripcion: str = Field(alias="Descripción Equipo")
    tag: str = Field(alias="TAG")
    falla_funcional: str = Field(alias="Falla Funcional")
    mecanismo: str = Field(alias="Mecanismo de Falla (ISO 14224)")
    modo: str = Field(alias="Modo de Falla (ISO 14224)")
    causa: str = Field(alias="Causa de la Falla (ISO 14224)")
    codigo_iso: str = Field(alias="Codigo ISO 14224")
    causa_raiz: str = Field(alias="Causa Raíz")
    patron: str = Field(alias="Patrón de Falla")
    efecto: str = Field(alias="Efecto de la Falla")
    evidente: str = Field(alias="Falla Evidente (ABCD)")
    oculta: str = Field(alias="Falla Oculta (AEFG)")
    seguridad: str = Field(alias="Seguridad")
    ambiente: str = Field(alias="Ambiente")
    operacional: str = Field(alias="Operacional")
    no_operacional: str = Field(alias="No Operacional")
    estrategia: str = Field(alias="Estrategia de Mantenimiento")
    severidad: int | str = Field(alias="Severidad")
    ocurrencia: int | str = Field(alias="Ocurrecia")  # sic — benchmark spelling
    deteccion: int | str = Field(alias="Deteccion")  # sic — benchmark spelling
    rpn: int | str = Field(alias="RPN")
    tarea: str = Field(alias="TAREA DE MANTENIMIENTO")
    frecuencia: str = Field(alias="FRECUENCIA DE LA TAREA")
    duracion: float | str = Field(alias="DURACION DE LA TAREA (HORAS)")
    ejecutor: str = Field(alias="EJECUTOR (DISCIPLINA)")
    requiere_paro: str = Field(alias="REQUIERE PARO DEL EQUIPO?")


class PlanRow(BaseModel):
    """One PLAN DE MANTENIMIENTO row. Strategy columns are one-hot marks."""

    modo: str = Field(alias="Modo de Falla (ISO 14224)")
    codigo_iso: str = Field(alias="Codigo ISO 14224")
    causa_raiz: str = Field(alias="Causa Raíz")
    patron: str = Field(alias="Patrón de Falla")
    efecto: str = Field(alias="Efecto de la Falla")
    evidente: str = Field(alias="Falla Evidente (ABCD)")
    oculta: str = Field(alias="Falla Oculta (AEFG)")
    seguridad: str = Field(alias="Seguridad")
    ambiente: str = Field(alias="Ambiente")
    operacional: str = Field(alias="Operacional")
    no_operacional: str = Field(alias="No Operacional")
    basado_condicion: str = Field(alias="Basado en Condición")
    preventivo: str = Field(alias="Preventivo")
    deteccion_fallas: str = Field(alias="Detección de Fallas")
    otras: str = Field(alias="Otros tipos de Estrategias (Rediseño, etc).")
    tarea: str = Field(alias="TAREA DE MANTENIMIENTO")
    frecuencia: str = Field(alias="FRECUENCIA DE LA TAREA")
    duracion: float | str = Field(alias="DURACION DE LA TAREA (HORAS)")
    ejecutor: str = Field(alias="EJECUTOR (DISCIPLINA)")
    requiere_paro: str = Field(alias="REQUIERE PARO DEL EQUIPO?")


def _mark(flag: bool) -> str:
    return X if flag else ""


def _effect_text(session: RCMSession, fmid: str) -> str:
    effect = session.effects.get(fmid)
    if effect is None:
        return ""
    return f"{effect.local}. {effect.system}. {effect.plant}."


def _es_oculta(effect: Effect | None, decision: DecisionResult | None) -> bool:
    """En qué columna cae el centinela: la que marca la visibilidad.

    `effect.is_hidden` es la fuente primaria. Sin `Effect` la visibilidad **no
    se pierde**: `DecisionResult.consequence_class` es obligatorio
    (`domain.py:226`) y `hidden_route` sólo se llena para fallas ocultas. Caer
    al `else` sin mirarlos hacía que el libro clasificara como *evidente* una
    falla que la propia decisión guardada declara *oculta*.
    """
    if effect is not None:
        return effect.is_hidden
    if decision is None:
        return False
    return (
        decision.consequence_class == ConsequenceClass.OCULTA
        or decision.hidden_route is not None
    )


def _contraste(
    effect: Effect | None, decision: DecisionResult | None
) -> tuple[tuple[str, str], tuple[str, str]] | None:
    """(ruta guardada, ruta recalculada), o `None` si no hay nada que contrastar.

    Único sitio del módulo que invoca `derive_route`. Lo comparten la
    proyección de las celdas y el registro de auditoría, que antes repetían la
    misma comparación y ya habían divergido en el caso `effect is None`.
    """
    if decision is None or effect is None:
        return None
    guardada = (decision.evident_route or "", decision.hidden_route or "")
    if guardada == ("", ""):
        return None
    calc_e, calc_o = derive_route(effect, MaintenancePolicy(decision.policy))
    return guardada, (calc_e or "", calc_o or "")


def _rutas(effect: Effect | None, decision: DecisionResult | None) -> tuple[str, str]:
    """Celdas (ABCD, AEFG). Sólo se imprime una letra que se pueda reproducir.

    No hay respaldo hacia `Effect.evident_route`/`hidden_route`: esos campos son
    válidos en el modelo pero el flujo de producción no los puebla, y la ruta es
    una conclusión de la lógica JA1011 cuyo único dueño legítimo es
    `DecisionResult`. Una ruta guardada en el efecto es un dato sin procedencia
    auditable.

    La letra guardada se contrasta contra `derive_route` antes de imprimirla:
    `DecisionResult` no valida coherencia con la visibilidad ni con la política,
    así que un estado histórico puede traer una «B» donde la lógica da «A». Ante
    el desacuerdo no se imprime ninguna de las dos —reescribir en silencio
    ocultaría que el estado está corrupto— y el caso se registra en AUDITORIA.
    Sin `Effect` tampoco se imprime: la regla es «toda letra impresa se puede
    reproducir», no «toda letra que no pude refutar se imprime».

    El centinela va en la columna que marca la visibilidad, nunca en las dos: la
    fila sigue diciendo lo que el análisis sí determinó —la falla es oculta— y
    declara pendiente sólo lo que falta, que es la letra.
    """
    guardada = (
        (decision.evident_route or "", decision.hidden_route or "")
        if decision is not None else ("", "")
    )
    contraste = _contraste(effect, decision)
    if contraste is not None and contraste[0] == contraste[1]:
        return contraste[0]  # la única salida que imprime letras
    if guardada != ("", ""):
        # Hay ruta guardada y no se pudo reproducir: o discrepa del recálculo, o
        # falta el efecto contra el cual recalcularla. Las dos son estado corrupto.
        pendiente = RUTA_INCONSISTENTE
    elif decision is not None:
        pendiente = DECISION_SIN_RUTA
    else:
        pendiente = SIN_DECISION
    return ("", pendiente) if _es_oculta(effect, decision) else (pendiente, "")


def _etiqueta_ruta(par: tuple[str, str]) -> str:
    """«evidente:A» / «oculta:A», no «A».

    La posición en la tupla es la mitad del dato: una ruta evidente A y una
    oculta A son distintas y se ven iguales si se aplana. El renglón de
    auditoría decía «guardada: A — contraste: A», o sea afirmaba una
    discrepancia mostrando dos veces el mismo valor.
    """
    evidente, oculta = par
    if evidente:
        return f"evidente:{evidente}"
    if oculta:
        return f"oculta:{oculta}"
    return "sin ruta"


def rutas_inconsistentes(session: RCMSession) -> list[tuple[str, str, str]]:
    """(modo, ruta guardada, ruta contrastada) para el registro de auditoría.

    Sólo modos creíbles: los demás no tienen fila en ninguna hoja, y el renglón
    de auditoría habla de «la fila» donde no se imprime la ruta.
    """
    desacuerdos: list[tuple[str, str, str]] = []
    for fmid, decision in session.decisions.items():
        fm = session.failure_modes.get(fmid)
        if fm is None or not fm.credible:
            continue
        effect = session.effects.get(fmid)
        guardada_cruda = (decision.evident_route or "", decision.hidden_route or "")
        if guardada_cruda == ("", ""):
            # Una decisión que perdió su ruta también es estado corrupto, y
            # antes se iba por este `continue` sin dejar rastro en ninguna hoja
            # — el mismo defecto que esta feature vino a arreglar, un piso más
            # abajo.
            desacuerdos.append((fmid, "sin ruta", "la decisión existe pero no registró ruta"))
            continue
        guardada = _etiqueta_ruta(guardada_cruda)
        if effect is None:
            desacuerdos.append((fmid, guardada, "sin efecto registrado"))
            continue
        contraste = _contraste(effect, decision)
        assert contraste is not None
        if contraste[0] != contraste[1]:
            desacuerdos.append((fmid, guardada, _etiqueta_ruta(contraste[1])))
    return desacuerdos


def _task_cells(task: MaintenanceTask | None) -> tuple[str, str, float | str, str, str]:
    if task is None:
        return "", "", "", "", ""
    return (
        task.description,
        task.frequency,
        task.duration_hours,
        task.discipline,
        "SI" if task.requires_shutdown else "NO",
    )


def _first_task(session: RCMSession, fmid: str) -> tuple[str, str, float | str, str, str]:
    """La celda de tarea de la hoja AMEF, que es una fila por modo de falla.

    Antes devolvía `tasks[0]` a secas. Con dos tareas registradas para el mismo
    modo, la hoja que el cliente abre primero mostraba una y callaba la otra —y
    en el caso real callaba justo la corregida—. La hoja AMEF no puede crecer a
    una fila por tarea sin dejar de ser el AMEF del cliente, así que dice la
    verdad de otra forma: las nombra todas y manda al plan para el detalle.
    """
    tasks = session.tasks.get(fmid, [])
    if len(tasks) <= 1:
        return _task_cells(tasks[0] if tasks else None)
    ver_el_plan = "Ver PLAN DE MANTENIMIENTO"
    return (
        " / ".join(t.description for t in tasks),
        ver_el_plan,
        ver_el_plan,
        ver_el_plan,
        ver_el_plan,
    )


def amef_rows_with_ids(session: RCMSession) -> list[tuple[str, AMEFRow]]:
    """Filas del AMEF junto a su `FM-id`.

    El id no puede ser un campo de `AMEFRow`: `amef_headers()` se construye con
    los alias del modelo y un golden test los compara verbatim contra el fixture
    del cliente, así que un campo más rompería el contrato del dialecto. Viaja
    aparte y `excel.py` lo escribe en la columna A, fuera del rango de
    encabezados. Y viaja desde acá, y no de un segundo recorrido, para que el
    filtro de credibilidad y el orden tengan una sola fuente de verdad.
    """
    rows: list[tuple[str, AMEFRow]] = []
    for fmid, fm in session.failure_modes.items():
        if not fm.credible:
            continue  # documented discards live in the audit sheet, not the AMEF
        ff = session.functional_failures[fm.functional_failure_id]
        effect = session.effects.get(fmid)
        score = session.risk_scores.get(fmid)
        decision = session.decisions.get(fmid)
        evidente, oculta = _rutas(effect, decision)
        tarea, frecuencia, duracion, ejecutor, paro = _first_task(session, fmid)
        rows.append((
            fmid,
            AMEFRow.model_validate({
                    "Familia del Equipo": session.scope.equipment_family,
                    "Descripción Equipo": session.scope.equipment_description,
                    "TAG": session.scope.tag,
                    # El código FF- va DENTRO de la celda: no hay una segunda
                    # columna libre y es el formato que pidió el interesado.
                    # El encabezado está congelado, el contenido no.
                    "Falla Funcional": f"{ff.id} — {ff.description}",
                    "Mecanismo de Falla (ISO 14224)": fm.mechanism,
                    "Modo de Falla (ISO 14224)": fm.description,
                    "Causa de la Falla (ISO 14224)": fm.cause,
                    "Codigo ISO 14224": fm.iso_code,
                    "Causa Raíz": fm.root_cause,
                    "Patrón de Falla": fm.failure_pattern,
                    "Efecto de la Falla": _effect_text(session, fmid),
                    "Falla Evidente (ABCD)": evidente,
                    "Falla Oculta (AEFG)": oculta,
                    "Seguridad": _mark(bool(effect and effect.safety)),
                    "Ambiente": _mark(bool(effect and effect.environment)),
                    "Operacional": _mark(bool(effect and effect.operational)),
                    "No Operacional": _mark(bool(effect and effect.non_operational)),
                    "Estrategia de Mantenimiento": decision.policy if decision else "",
                    "Severidad": score.severity if score else "",
                    "Ocurrecia": score.occurrence if score else "",
                    "Deteccion": score.detection if score else "",
                    "RPN": score.rpn if score else "",
                    "TAREA DE MANTENIMIENTO": tarea,
                    "FRECUENCIA DE LA TAREA": frecuencia,
                    "DURACION DE LA TAREA (HORAS)": duracion,
                    "EJECUTOR (DISCIPLINA)": ejecutor,
                    "REQUIERE PARO DEL EQUIPO?": paro,
                }
            ),
        ))
    return rows


def to_amef_rows(session: RCMSession) -> list[AMEFRow]:
    return [row for _, row in amef_rows_with_ids(session)]


def plan_rows_with_ids(session: RCMSession) -> list[tuple[str, PlanRow]]:
    """One PLAN row per (failure mode, task) — no task is ever dropped. Modes with a
    decision but no scheduled task (e.g. OHF) still emit one row with empty task cells.

    Un modo creíble SIN decisión también emite su fila. Antes se lo saltaba en
    silencio: la hoja salía con 49 filas contra las 60 del AMEF y no había en
    todo el libro nada que dijera qué se había caído ni por qué. En la sesión
    real eso escondía 8 de las 11 fallas ocultas y todas las de seguridad sin
    decidir. Un entregable auditable no desaparece datos; los marca.
    """
    rows: list[tuple[str, PlanRow]] = []
    for fmid, fm in session.failure_modes.items():
        if not fm.credible:
            continue
        decision = session.decisions.get(fmid)
        effect = session.effects.get(fmid)
        evidente, oculta = _rutas(effect, decision)
        plan_col = (
            POLICY_PLAN_COLUMN.get(MaintenancePolicy(decision.policy), "") if decision else ""
        )
        tasks: list[MaintenanceTask | None] = list(session.tasks.get(fmid, []))
        if not tasks:
            tasks = [None]
        for task in tasks:
            tarea, frecuencia, duracion, ejecutor, paro = _task_cells(task)
            rows.append((
            fmid,
            PlanRow.model_validate({
                    "Modo de Falla (ISO 14224)": fm.description,
                    "Codigo ISO 14224": fm.iso_code,
                    "Causa Raíz": fm.root_cause,
                    "Patrón de Falla": fm.failure_pattern,
                    "Efecto de la Falla": _effect_text(session, fmid),
                    "Falla Evidente (ABCD)": evidente,
                    "Falla Oculta (AEFG)": oculta,
                    "Seguridad": _mark(bool(effect and effect.safety)),
                    "Ambiente": _mark(bool(effect and effect.environment)),
                    "Operacional": _mark(bool(effect and effect.operational)),
                    "No Operacional": _mark(bool(effect and effect.non_operational)),
                    "Basado en Condición": _mark(plan_col == "Basado en Condición"),
                    "Preventivo": _mark(plan_col == "Preventivo"),
                    "Detección de Fallas": _mark(plan_col == "Detección de Fallas"),
                    "Otros tipos de Estrategias (Rediseño, etc).": _mark(
                        plan_col == "Otros tipos de Estrategias (Rediseño, etc)."
                    ),
                    "TAREA DE MANTENIMIENTO": tarea,
                    "FRECUENCIA DE LA TAREA": frecuencia,
                    "DURACION DE LA TAREA (HORAS)": duracion,
                    "EJECUTOR (DISCIPLINA)": ejecutor,
                    "REQUIERE PARO DEL EQUIPO?": paro,
                }
            ),
        ))
    return rows


def to_plan_rows(session: RCMSession) -> list[PlanRow]:
    return [row for _, row in plan_rows_with_ids(session)]


def amef_headers() -> list[str]:
    return [f.alias or name for name, f in AMEFRow.model_fields.items()]


def plan_headers() -> list[str]:
    return [f.alias or name for name, f in PlanRow.model_fields.items()]
