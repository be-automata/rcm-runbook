"""RCM decision logic — deterministic JA1011/JA1012 cascade. Zero LLM.

Cascade (per RCM handbook decision tree + domain review corrections):
  0. Credibility screen — non-credible modes exit with documented discard.
  1. Evident vs hidden.
  2. Consequence class: Seguridad/Ambiente (SE) > Operacional > No operacional;
     hidden modes classify as OCULTA (their multiple-failure consequence still
     drives severity of treatment).
  3. Strategy cascade, first applicable-and-effective wins:
       automated monitoring / on-condition (MBC)   — needs sufficient P-F interval
       scheduled restoration (MBT)                 — needs non-stochastic aging + viable
       scheduled relubrication (ReP)               — aging-driven lubrication consumption
       failure finding (BF)                        — hidden modes fallback
       redesign (Rd)                               — MANDATORY when SE (safety OR
                                                     environmental) has no applicable task
       run-to-failure (OHF)                        — only when consequences are tolerable
  Hidden modes may validly receive MBC/MBT/ReP when applicable; BF is the fallback;
  Rd is mandatory only when a hidden safety/env multiple-failure has nothing applicable.
  A hidden mode with safety/env multiple-failure consequence can never resolve to OHF.

Route letters (client dialect): derived from evident/hidden + consequence class —
never free input. Provisional mapping (client to confirm):
  Evident: A=SE, B=Operacional, C=No operacional, D=run-to-failure tolerable
  Hidden:  A=SE multiple failure, E=Operacional, F=No operacional, G=tolerable

Interval rules: on-condition inspection ≤ P-F/2; restoration/discard ≈ 0.9·η.

HITL: SE consequences require human confirmation before the decision is final —
this engine raises HITLRequired; the session aggregate owns the ledger.
"""

from __future__ import annotations

from pydantic import BaseModel

from rcm_runbook.models.catalogs import (
    ConsequenceClass,
    EvidentRoute,
    FailurePattern,
    HiddenRoute,
    MaintenancePolicy,
)
from rcm_runbook.models.domain import DecisionResult, Effect, FailureMode


class HITLRequired(Exception):
    """The decision needs human confirmation (safety/environmental consequence)."""

    def __init__(self, failure_mode_id: str, reason_es: str) -> None:
        self.failure_mode_id = failure_mode_id
        self.reason_es = reason_es
        super().__init__(reason_es)


class DecisionAnswers(BaseModel):
    """Facilitator-collected answers that feed the deterministic cascade."""

    automated_monitoring_available: bool = False
    pf_interval_sufficient: bool = False  # P-F long enough for inspection + corrective lead time
    aging_related: bool = False  # non-stochastic wear-out (Fin de Vida Útil)
    restoration_feasible: bool = False
    lubrication_related: bool = False
    failure_finding_feasible: bool = False  # hidden only: can the failure be found by a test?
    redesign_identified: bool = False
    consequences_tolerable: bool = False  # OHF acceptable (economic judgement)


AGING_PATTERNS = {FailurePattern.FIN_DE_VIDA_UTIL, FailurePattern.ALEATORIA_FIN_DE_VIDA_UTIL}


def classify_consequence(effect: Effect) -> ConsequenceClass:
    if effect.is_hidden:
        return ConsequenceClass.OCULTA
    if effect.safety or effect.environment:
        return ConsequenceClass.SEGURIDAD_AMBIENTE
    if effect.operational:
        return ConsequenceClass.OPERACIONAL
    return ConsequenceClass.NO_OPERACIONAL


def derive_route(
    effect: Effect, policy: MaintenancePolicy
) -> tuple[EvidentRoute | None, HiddenRoute | None]:
    """Route letters are a function of visibility + consequence — never free input."""
    se = effect.safety or effect.environment
    if effect.is_hidden:
        if se:
            return None, HiddenRoute.A
        if policy == MaintenancePolicy.OHF:
            return None, HiddenRoute.G
        if effect.operational:
            return None, HiddenRoute.E
        return None, HiddenRoute.F
    if se:
        return EvidentRoute.A, None
    if policy == MaintenancePolicy.OHF:
        return EvidentRoute.D, None
    if effect.operational:
        return EvidentRoute.B, None
    return EvidentRoute.C, None


def _proactive_policy(
    fm: FailureMode, answers: DecisionAnswers
) -> tuple[MaintenancePolicy | None, str]:
    """First applicable proactive task in cascade order, with Spanish rationale."""
    if answers.automated_monitoring_available or (
        answers.pf_interval_sufficient and fm.pf_interval_hours
    ):
        # Only cite the P-F interval when the team judged it sufficient — an
        # automated-monitoring selection must not prescribe an inspection interval
        # derived from a P-F the team declared insufficient.
        detail = (
            f"intervalo P-F de {fm.pf_interval_hours:.0f} h con inspección ≤ P-F/2 "
            f"({fm.pf_interval_hours / 2:.0f} h)"
            if answers.pf_interval_sufficient and fm.pf_interval_hours
            else "monitoreo automatizado disponible"
        )
        return MaintenancePolicy.MBC, f"Falla detectable antes del fallo funcional: {detail}."
    if answers.pf_interval_sufficient:
        return (
            MaintenancePolicy.MBC,
            "Existe síntoma detectable con intervalo P-F suficiente (inspección ≤ P-F/2).",
        )
    if answers.lubrication_related and fm.failure_pattern in AGING_PATTERNS:
        return (
            MaintenancePolicy.REP,
            "Degradación por consumo de lubricante con patrón de envejecimiento: "
            "relubricación programada.",
        )
    if answers.aging_related and answers.restoration_feasible:
        interval = (
            f" Intervalo sugerido ≈ 0.9·η = {0.9 * fm.weibull_eta_hours:.0f} h."
            if fm.weibull_eta_hours
            else ""
        )
        return (
            MaintenancePolicy.MBT,
            "Patrón de fin de vida útil con restauración/sustitución programada viable."
            + interval,
        )
    return None, ""


def decide(fm: FailureMode, effect: Effect, answers: DecisionAnswers) -> DecisionResult:
    """Run the cascade. Raises HITLRequired for SE consequences (caller confirms first)."""
    if not fm.credible:
        raise ValueError(
            f"El modo {fm.id} fue descartado por no credibilidad "
            f"({fm.non_credible_discard}). No requiere política de mantenimiento."
        )

    consequence = classify_consequence(effect)
    se = effect.safety or effect.environment

    policy, rationale = _proactive_policy(fm, answers)

    if policy is None and effect.is_hidden:
        if answers.failure_finding_feasible:
            policy = MaintenancePolicy.BF
            rationale = (
                "Falla oculta sin tarea proactiva aplicable: búsqueda de fallas para "
                "verificar disponibilidad de la función de protección (intervalo por FFI)."
            )
        elif se:
            policy = MaintenancePolicy.RD
            rationale = (
                "Falla oculta con consecuencia de seguridad/ambiente en la falla múltiple "
                "y sin tarea aplicable: el rediseño es OBLIGATORIO (JA1011)."
            )

    if policy is None and se:
        # Evident safety/environmental with no applicable proactive task → redesign mandatory
        policy = MaintenancePolicy.RD
        rationale = (
            "Consecuencia de seguridad/ambiente sin tarea proactiva aplicable: "
            "el rediseño es OBLIGATORIO — nunca operar hasta la falla (JA1011)."
        )

    if policy is None:
        if answers.redesign_identified:
            policy = MaintenancePolicy.RD
            rationale = (
                "Sin tarea proactiva aplicable; existe rediseño identificado que "
                "elimina la causa."
            )
        elif answers.consequences_tolerable:
            policy = MaintenancePolicy.OHF
            rationale = (
                "Sin tarea proactiva aplicable y consecuencias económicas tolerables: "
                "operar hasta la falla, con justificación documentada."
            )
        else:
            # No applicable task AND the team did not judge consequences tolerable
            # (nor BF feasible for hidden modes): the engine must not invent a
            # definitive policy — the facilitator needs more answers.
            pending = (
                "factibilidad de búsqueda de fallas (failure_finding_feasible), "
                if effect.is_hidden
                else ""
            )
            raise ValueError(
                "No hay política determinable con las respuestas dadas: ninguna tarea "
                "proactiva es aplicable y no se confirmó que las consecuencias sean "
                f"tolerables. Aclare con el equipo: {pending}"
                "posibilidad de rediseño (redesign_identified) o tolerabilidad económica "
                "(consequences_tolerable), y vuelva a ejecutar la lógica de decisión."
            )

    # Guard: hidden or evident SE can never be OHF
    if policy == MaintenancePolicy.OHF and se:
        policy = MaintenancePolicy.RD
        rationale = (
            "Corrección: consecuencia de seguridad/ambiente no admite operar hasta la falla; "
            "se requiere rediseño u otra tarea aplicable (JA1011)."
        )

    if se:
        raise HITLRequired(
            fm.id,
            f"El modo {fm.id} tiene consecuencia de SEGURIDAD/AMBIENTE "
            f"(política propuesta: {policy.value} — {rationale}) "
            "Se requiere confirmación humana explícita antes de registrar la decisión.",
        )

    evident_route, hidden_route = derive_route(effect, policy)
    return DecisionResult(
        failure_mode_id=fm.id,
        consequence_class=consequence,
        policy=policy,
        justification=rationale,
        evident_route=evident_route,
        hidden_route=hidden_route,
        provisional=policy in (MaintenancePolicy.EXED, MaintenancePolicy.CC),
    )


def decide_confirmed(
    fm: FailureMode, effect: Effect, answers: DecisionAnswers, approver: str
) -> DecisionResult:
    """Same cascade for SE consequences after human confirmation."""
    try:
        return decide(fm, effect, answers)
    except HITLRequired:
        pass
    # Re-run the internal logic knowing HITL is satisfied
    consequence = classify_consequence(effect)
    policy, rationale = _proactive_policy(fm, answers)
    if policy is None:
        if effect.is_hidden and answers.failure_finding_feasible:
            policy, rationale = (
                MaintenancePolicy.BF,
                "Falla oculta con consecuencia seguridad/ambiente: búsqueda de fallas aplicable "
                "(intervalo por FFI); confirmado por revisión humana.",
            )
        else:
            policy, rationale = (
                MaintenancePolicy.RD,
                "Consecuencia de seguridad/ambiente sin tarea aplicable: rediseño obligatorio; "
                "confirmado por revisión humana.",
            )
    evident_route, hidden_route = derive_route(effect, policy)
    return DecisionResult(
        failure_mode_id=fm.id,
        consequence_class=consequence,
        policy=policy,
        justification=rationale,
        evident_route=evident_route,
        hidden_route=hidden_route,
        provisional=policy in (MaintenancePolicy.EXED, MaintenancePolicy.CC),
        hitl_confirmed_by=approver,
    )
