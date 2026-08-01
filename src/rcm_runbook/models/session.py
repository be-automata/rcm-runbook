"""RCMSession — the aggregate. All mutations go through intention-revealing methods
that generate stable sequential IDs, enforce referential integrity, and surface
errors in Spanish. Serialization crosses exactly one boundary:
`RCMSession.model_validate()` / `model_dump(mode="json")`.
"""

from __future__ import annotations

import re
import unicodedata
from enum import IntEnum
from typing import Any

from pydantic import BaseModel, Field

from rcm_runbook.errors import ReglaDeNegocio
from rcm_runbook.models.domain import (
    Control,
    DecisionResult,
    Effect,
    FailureMode,
    Function,
    FunctionalFailure,
    FunctionKind,
    MaintenanceTask,
    RecommendedAction,
    RiskScore,
    failure_mode_snapshot,
)

SCHEMA_VERSION = 1


class Phase(IntEnum):
    P1_ALCANCE = 1
    P2_FUNCIONES = 2
    P3_AMEF = 3
    P4_RIESGO = 4
    P5_DECISION = 5
    P6_PLAN = 6
    COMPLETADO = 7


PHASE_NAMES_ES: dict[Phase, str] = {
    Phase.P1_ALCANCE: "Alcance y contexto",
    Phase.P2_FUNCIONES: "Funciones y fallas funcionales",
    Phase.P3_AMEF: "AMEF: modos, efectos, causas y controles",
    Phase.P4_RIESGO: "Valoración del riesgo (S/O/D)",
    Phase.P5_DECISION: "Decisión RCM y acciones",
    Phase.P6_PLAN: "Plan de mantenimiento, validación y KPIs",
    Phase.COMPLETADO: "Análisis completado",
}


class ReferentialIntegrityError(ValueError):
    """Raised (in Spanish) when a tool references an unknown entity id."""


class StaleDecisionError(ValueError):
    """Raised when a score/decision was computed from inputs that changed afterwards."""


class ScopeMeta(BaseModel):
    equipment_family: str = ""
    equipment_description: str = ""
    tag: str = ""
    location: str = ""
    boundaries: str = ""
    interfaces: str = ""
    normal_conditions: str = ""
    objective: str = ""
    operating_context: str = ""


class TeamMember(BaseModel):
    name: str
    role: str


class HITLRecord(BaseModel):
    failure_mode_id: str
    reason: str
    requested_at_turn: int = 0
    confirmed_by: str | None = None


class KPI(BaseModel):
    name: str
    target: str = ""


class RCMSession(BaseModel):
    schema_version: int = SCHEMA_VERSION
    phase: Phase = Phase.P1_ALCANCE
    scope: ScopeMeta = Field(default_factory=ScopeMeta)
    team: list[TeamMember] = Field(default_factory=list)
    info_sources: list[str] = Field(default_factory=list)
    # Explicit confirmations required by P2 gate (protective functions are where
    # hidden failures live — the interview must ask even if the answer is "none")
    secondary_functions_confirmed: bool = False
    protective_functions_confirmed: bool = False

    functions: dict[str, Function] = Field(default_factory=dict)
    functional_failures: dict[str, FunctionalFailure] = Field(default_factory=dict)
    failure_modes: dict[str, FailureMode] = Field(default_factory=dict)
    effects: dict[str, Effect] = Field(default_factory=dict)  # keyed by failure_mode_id
    controls: dict[str, list[Control]] = Field(default_factory=dict)
    risk_scores: dict[str, RiskScore] = Field(default_factory=dict)
    residual_scores: dict[str, RiskScore] = Field(default_factory=dict)
    decisions: dict[str, DecisionResult] = Field(default_factory=dict)
    actions: dict[str, list[RecommendedAction]] = Field(default_factory=dict)
    tasks: dict[str, list[MaintenanceTask]] = Field(default_factory=dict)

    kpis: list[KPI] = Field(default_factory=list)
    review_triggers: list[str] = Field(default_factory=list)
    validation_signoff: str = ""
    hitl_ledger: list[HITLRecord] = Field(default_factory=list)

    # ------------------------------------------------------------------
    # ID generation & lookups
    # ------------------------------------------------------------------

    def _next_id(self, prefix: str, existing: dict[str, Any]) -> str:
        return f"{prefix}-{len(existing) + 1:03d}"

    def _require(self, entity: str, key: str, collection: dict[str, Any]) -> None:
        if key not in collection:
            known = ", ".join(sorted(collection)) or "ninguno registrado"
            raise ReferentialIntegrityError(
                f"No existe {entity} con id '{key}'. Registrados: {known}."
            )

    # ------------------------------------------------------------------
    # Intention-revealing mutators
    # ------------------------------------------------------------------

    @staticmethod
    def _sin_acentos(t: str) -> str:
        plano = unicodedata.normalize("NFKD", t)
        return "".join(c for c in plano if not unicodedata.combining(c))

    @staticmethod
    def _normalizar(t: str) -> str:
        """Baja el texto a sus palabras: sin acentos, sin puntuación, sin
        paréntesis explicativos y sin espacios de más. Solo para _casi_igual —
        aplicarlo también a _same_text haría pasar por «la misma llamada» una
        corrección con paréntesis, y se descartaría el dato corregido."""
        sin_parentesis = re.sub(r"\([^)]*\)", " ", t)
        plano = RCMSession._sin_acentos(sin_parentesis)
        return " ".join(re.sub(r"[^\w\s]", " ", plano).casefold().split())

    @staticmethod
    def _same_text(a: str, b: str) -> bool:
        """El mismo texto: el LLM repite la llamada literal tras un error de
        validación y no debe duplicar la entidad. Nada más que mayúsculas,
        acentos y espacios."""
        return " ".join(RCMSession._sin_acentos(a).casefold().split()) == " ".join(
            RCMSession._sin_acentos(b).casefold().split()
        )

    @staticmethod
    def _casi_igual(a: str, b: str) -> bool:
        """Casi lo mismo, pero no igual — el caso que el guardián no veía.

        El docstring prometía «near-duplicate» y el código comparaba texto
        exacto. Bastaba con que el modelo reformulara para colar una segunda
        tarea del mismo modo: en el primer análisis completo real salieron dos
        filas contradictorias («1 h, no requiere paro» y «3 h, sí requiere
        paro») y la hoja AMEF mostró en silencio la equivocada.

        No se fusionan solas: fusionar a ciegas borraría una tarea legítima
        distinta. Quien llama decide, y aquí solo se responde a la pregunta.
        """
        na, nb = RCMSession._normalizar(a), RCMSession._normalizar(b)
        if not na or not nb:
            return False
        if na == nb:
            return True
        # Una descripción contenida en la otra es reformulación, no otra tarea:
        # «…rodamientos de bomba P-101 (cojinetes motor y bomba)» vs «…P-101».
        if na in nb or nb in na:
            return True
        ta, tb = set(na.split()), set(nb.split())
        return len(ta & tb) / len(ta | tb) >= 0.8

    def add_function(self, **kwargs: Any) -> Function:
        candidate = Function(id="F-000", **kwargs)
        for existing in self.functions.values():
            if existing.kind == candidate.kind and self._same_text(
                f"{existing.verb} {existing.object}", f"{candidate.verb} {candidate.object}"
            ):
                return existing  # ya registrada — idempotente
        fid = self._next_id("F", self.functions)
        fn = candidate.model_copy(update={"id": fid})
        self.functions[fid] = fn
        if fn.kind == FunctionKind.SECUNDARIA:
            self.secondary_functions_confirmed = True
        if fn.kind == FunctionKind.PROTECCION:
            self.protective_functions_confirmed = True
        return fn

    def confirm_no_functions_of_kind(self, kind: FunctionKind) -> None:
        """Record the explicit 'no hay' answer for secondary/protective functions."""
        if kind == FunctionKind.SECUNDARIA:
            self.secondary_functions_confirmed = True
        elif kind == FunctionKind.PROTECCION:
            self.protective_functions_confirmed = True

    def add_functional_failure(self, function_id: str, description: str) -> FunctionalFailure:
        self._require("función", function_id, self.functions)
        for existing in self.functional_failures.values():
            if existing.function_id == function_id and self._same_text(
                existing.description, description
            ):
                return existing  # idempotente
        ffid = self._next_id("FF", self.functional_failures)
        ff = FunctionalFailure(id=ffid, function_id=function_id, description=description)
        self.functional_failures[ffid] = ff
        return ff

    def add_failure_mode(self, functional_failure_id: str, **kwargs: Any) -> FailureMode:
        self._require("falla funcional", functional_failure_id, self.functional_failures)
        candidate = FailureMode(
            id="FM-000", functional_failure_id=functional_failure_id, **kwargs
        )
        for existing in self.failure_modes.values():
            if existing.functional_failure_id == functional_failure_id and self._same_text(
                existing.description, candidate.description
            ):
                return existing  # idempotente — el reintento del LLM no duplica
        fmid = self._next_id("FM", self.failure_modes)
        fm = candidate.model_copy(update={"id": fmid})
        self.failure_modes[fmid] = fm
        return fm

    def update_failure_mode(self, failure_mode_id: str, **updates: Any) -> FailureMode:
        self._require("modo de falla", failure_mode_id, self.failure_modes)
        fm = self.failure_modes[failure_mode_id].model_copy(update=updates)
        FailureMode.model_validate(fm.model_dump())  # re-run validators
        self.failure_modes[failure_mode_id] = fm
        return fm

    def set_effect(self, failure_mode_id: str, **kwargs: Any) -> Effect:
        self._require("modo de falla", failure_mode_id, self.failure_modes)
        effect = Effect(failure_mode_id=failure_mode_id, **kwargs)
        self.effects[failure_mode_id] = effect
        return effect

    def add_control(self, failure_mode_id: str, **kwargs: Any) -> Control:
        self._require("modo de falla", failure_mode_id, self.failure_modes)
        control = Control(failure_mode_id=failure_mode_id, **kwargs)
        self.controls.setdefault(failure_mode_id, []).append(control)
        return control

    def set_risk_score(self, score: RiskScore) -> None:
        self._require("modo de falla", score.failure_mode_id, self.failure_modes)
        target = self.residual_scores if score.is_residual else self.risk_scores
        target[score.failure_mode_id] = score

    def set_decision(self, decision: DecisionResult) -> None:
        self._require("modo de falla", decision.failure_mode_id, self.failure_modes)
        self.decisions[decision.failure_mode_id] = decision

    def add_action(self, action: RecommendedAction) -> None:
        self._require("modo de falla", action.failure_mode_id, self.failure_modes)
        self.actions.setdefault(action.failure_mode_id, []).append(action)

    def add_task(self, task: MaintenanceTask) -> None:
        self._require("modo de falla", task.failure_mode_id, self.failure_modes)
        existing_tasks = self.tasks.setdefault(task.failure_mode_id, [])
        campos = ("frequency", "duration_hours", "discipline", "requires_shutdown")
        for existing in existing_tasks:
            if self._same_text(existing.description, task.description):
                if all(getattr(existing, c) == getattr(task, c) for c in campos):
                    return  # idempotente: la misma llamada, otra vez
                # Mismo texto y distintos datos es una corrección, no un
                # reintento. Quedarse con la primera en silencio deja en el plan
                # el dato viejo justo cuando alguien intentaba arreglarlo.
                raise ReglaDeNegocio(
                    f"Ya hay una tarea con esa misma descripción para "
                    f"{task.failure_mode_id}, pero con otros datos: "
                    f"'{existing.description}' ({existing.frequency}, "
                    f"{existing.duration_hours} h, "
                    f"{'requiere paro' if existing.requires_shutdown else 'sin paro'}). "
                    "Si quieres corregirla, dilo explícitamente; si es otra "
                    "tarea, dale una descripción que las distinga."
                )
            if self._casi_igual(existing.description, task.description):
                # Ni se duplica ni se fusiona en silencio: las dos salidas
                # calladas producen un plan de mantenimiento en el que el
                # cliente no puede confiar. Se devuelve la pelota con el dato
                # concreto para que quien sabe decida.
                raise ReglaDeNegocio(
                    f"Ya hay una tarea casi idéntica para {task.failure_mode_id}: "
                    f"'{existing.description}' ({existing.frequency}, "
                    f"{existing.duration_hours} h, "
                    f"{'requiere paro' if existing.requires_shutdown else 'sin paro'}). "
                    f"La nueva sería '{task.description}' ({task.frequency}, "
                    f"{task.duration_hours} h, "
                    f"{'requiere paro' if task.requires_shutdown else 'sin paro'}). "
                    "Si es la misma tarea corregida, dilo y la reemplazo; si son "
                    "dos tareas distintas, diferencia las descripciones."
                )
        existing_tasks.append(task)

    # ------------------------------------------------------------------
    # HITL ledger (sole writers)
    # ------------------------------------------------------------------

    def request_hitl(self, failure_mode_id: str, reason: str) -> HITLRecord:
        for rec in self.hitl_ledger:
            if rec.failure_mode_id == failure_mode_id and rec.confirmed_by is None:
                return rec
        rec = HITLRecord(failure_mode_id=failure_mode_id, reason=reason)
        self.hitl_ledger.append(rec)
        return rec

    def confirm_hitl(self, failure_mode_id: str, approver: str) -> HITLRecord:
        for rec in self.hitl_ledger:
            if rec.failure_mode_id == failure_mode_id and rec.confirmed_by is None:
                rec.confirmed_by = approver
                return rec
        raise ReferentialIntegrityError(
            f"No hay solicitud de confirmación humana pendiente para '{failure_mode_id}'."
        )

    def hitl_confirmed(self, failure_mode_id: str) -> bool:
        return any(
            r.failure_mode_id == failure_mode_id and r.confirmed_by for r in self.hitl_ledger
        )

    # ------------------------------------------------------------------
    # Staleness
    # ------------------------------------------------------------------

    def current_snapshot(self, failure_mode_id: str) -> str:
        fm = self.failure_modes[failure_mode_id]
        return failure_mode_snapshot(
            fm, self.effects.get(failure_mode_id), self.controls.get(failure_mode_id)
        )

    def stale_decisions(self) -> list[str]:
        """Failure-mode ids whose score/decision inputs changed after computation."""
        stale: set[str] = set()
        for fmid, decision in self.decisions.items():
            if decision.input_hash and decision.input_hash != self.current_snapshot(fmid):
                stale.add(fmid)
        for scores in (self.risk_scores, self.residual_scores):
            for fmid, score in scores.items():
                if score.input_hash and score.input_hash != self.current_snapshot(fmid):
                    stale.add(fmid)
        return sorted(stale)

    # ------------------------------------------------------------------
    # Digest (compact Spanish state summary injected into agent context)
    # ------------------------------------------------------------------

    def digest_es(self) -> str:
        lines = [
            f"FASE ACTUAL: {self.phase.value}/6 — {PHASE_NAMES_ES[self.phase]}",
            f"Activo: {self.scope.equipment_description or '—'} (TAG: {self.scope.tag or '—'})",
            f"Equipo de trabajo: {len(self.team)} integrantes",
        ]
        if self.functions:
            lines.append("Funciones: " + "; ".join(
                f"{f.id}[{f.kind.value[:4]}] {f.verb} {f.object}" for f in self.functions.values()
            ))
        if self.functional_failures:
            lines.append("Fallas funcionales: " + "; ".join(
                f"{ff.id}→{ff.function_id}" for ff in self.functional_failures.values()
            ))
        if self.failure_modes:
            parts = []
            for fm in self.failure_modes.values():
                score = self.risk_scores.get(fm.id)
                dec = self.decisions.get(fm.id)
                extra = ""
                if score:
                    extra += f" RPN={score.rpn}"
                if dec:
                    extra += f" →{dec.policy.value}"
                if not fm.credible:
                    extra += " [descartado: no creíble]"
                parts.append(f"{fm.id} {fm.description[:44]}{extra}")
            lines.append("Modos de falla: " + " | ".join(parts))
        stale = self.stale_decisions()
        if stale:
            lines.append(f"⚠ Decisiones desactualizadas (re-evaluar): {', '.join(stale)}")
        pending = [r.failure_mode_id for r in self.hitl_ledger if not r.confirmed_by]
        if pending:
            lines.append(f"⚠ Confirmación humana pendiente: {', '.join(pending)}")
        return "\n".join(lines)
