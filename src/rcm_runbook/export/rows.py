"""Export read-models — the export context owns the client's Excel dialect.

`AMEFRow`/`PlanRow` field order == benchmark column order (frozen fixture);
a golden test enforces the alias↔header match, so the domain model and the
deliverable can never drift independently. Row grain: one row per credible
failure mode (matching the benchmark; non-credible modes appear only in the
audit sheet with their documented discard).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from rcm_runbook.models.catalogs import (
    POLICY_PLAN_COLUMN,
    MaintenancePolicy,
)
from rcm_runbook.models.session import RCMSession

X = "X"  # benchmark marks consequence/strategy flags with X


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


def _first_task(session: RCMSession, fmid: str) -> tuple[str, str, float | str, str, str]:
    tasks = session.tasks.get(fmid, [])
    if not tasks:
        return "", "", "", "", ""
    t = tasks[0]
    return (
        t.description,
        t.frequency,
        t.duration_hours,
        t.discipline,
        "SI" if t.requires_shutdown else "NO",
    )


def to_amef_rows(session: RCMSession) -> list[AMEFRow]:
    rows: list[AMEFRow] = []
    for fmid, fm in session.failure_modes.items():
        if not fm.credible:
            continue  # documented discards live in the audit sheet, not the AMEF
        ff = session.functional_failures[fm.functional_failure_id]
        effect = session.effects.get(fmid)
        score = session.risk_scores.get(fmid)
        decision = session.decisions.get(fmid)
        tarea, frecuencia, duracion, ejecutor, paro = _first_task(session, fmid)
        rows.append(
            AMEFRow.model_validate({
                    "Familia del Equipo": session.scope.equipment_family,
                    "Descripción Equipo": session.scope.equipment_description,
                    "TAG": session.scope.tag,
                    "Falla Funcional": ff.description,
                    "Mecanismo de Falla (ISO 14224)": fm.mechanism,
                    "Modo de Falla (ISO 14224)": fm.description,
                    "Causa de la Falla (ISO 14224)": fm.cause,
                    "Codigo ISO 14224": fm.iso_code,
                    "Causa Raíz": fm.root_cause,
                    "Patrón de Falla": fm.failure_pattern,
                    "Efecto de la Falla": _effect_text(session, fmid),
                    "Falla Evidente (ABCD)": (
                        decision.evident_route or "" if decision
                        else (effect.evident_route or "" if effect else "")
                    ),
                    "Falla Oculta (AEFG)": (
                        decision.hidden_route or "" if decision
                        else (effect.hidden_route or "" if effect else "")
                    ),
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
            )
        )
    return rows


def to_plan_rows(session: RCMSession) -> list[PlanRow]:
    rows: list[PlanRow] = []
    for fmid, fm in session.failure_modes.items():
        if not fm.credible:
            continue
        decision = session.decisions.get(fmid)
        if decision is None:
            continue
        effect = session.effects.get(fmid)
        plan_col = POLICY_PLAN_COLUMN.get(MaintenancePolicy(decision.policy), "")
        tarea, frecuencia, duracion, ejecutor, paro = _first_task(session, fmid)
        rows.append(
            PlanRow.model_validate({
                    "Modo de Falla (ISO 14224)": fm.description,
                    "Codigo ISO 14224": fm.iso_code,
                    "Causa Raíz": fm.root_cause,
                    "Patrón de Falla": fm.failure_pattern,
                    "Efecto de la Falla": _effect_text(session, fmid),
                    "Falla Evidente (ABCD)": decision.evident_route or "",
                    "Falla Oculta (AEFG)": decision.hidden_route or "",
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
            )
        )
    return rows


def amef_headers() -> list[str]:
    return [f.alias or name for name, f in AMEFRow.model_fields.items()]


def plan_headers() -> list[str]:
    return [f.alias or name for name, f in PlanRow.model_fields.items()]
