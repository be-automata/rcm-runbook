"""Risk scoring — pure S/O/D arithmetic per SAE J1739. No LLM, no cross-entity rules.

The benchmark AMEF sheet carries Severidad / Ocurrecia / Deteccion / RPN columns,
so RPN is the deliverable's priority number. Cross-entity invariants (e.g.
residual-S invariance without redesign) live in engine/compliance.py.
"""

from __future__ import annotations

from pydantic import BaseModel

from rcm_runbook.models.catalogs import (
    SAE_DETECTION_ES,
    SAE_OCCURRENCE_ES,
    SAE_SEVERITY_ES,
)
from rcm_runbook.models.domain import RiskScore

HIGH_SEVERITY_THRESHOLD = 9


class ScoreSummary(BaseModel):
    failure_mode_id: str
    sod: str
    rpn: int
    so: int
    priority_es: str
    caveats_es: list[str]


def summarize(score: RiskScore) -> ScoreSummary:
    caveats: list[str] = []
    if score.severity >= HIGH_SEVERITY_THRESHOLD:
        caveats.append(
            f"Severidad {score.severity} (≥{HIGH_SEVERITY_THRESHOLD}): este modo de falla "
            "SIEMPRE debe atenderse, independientemente del RPN (SAE J1739)."
        )
    if score.detection >= 8:
        caveats.append(
            "Detección muy pobre (≥8): considere agregar capacidad de detección "
            "(monitorización, alarmas) además de la política seleccionada."
        )
    priority = _priority_es(score)
    return ScoreSummary(
        failure_mode_id=score.failure_mode_id,
        sod=score.sod,
        rpn=score.rpn,
        so=score.so,
        priority_es=priority,
        caveats_es=caveats,
    )


def _priority_es(score: RiskScore) -> str:
    if score.severity >= HIGH_SEVERITY_THRESHOLD:
        return "Crítica (severidad alta — atención obligatoria)"
    if score.rpn >= 200:
        return "Alta"
    if score.rpn >= 100:
        return "Media"
    if score.rpn >= 40:
        return "Baja"
    return "Muy baja"


def anchor_es(dimension: str, value: int) -> str:
    """Exact Spanish anchor text for an S/O/D rating (quoted to stakeholders)."""
    tables = {
        "severidad": SAE_SEVERITY_ES,
        "ocurrencia": SAE_OCCURRENCE_ES,
        "deteccion": SAE_DETECTION_ES,
    }
    table = tables.get(dimension.lower().replace("ó", "o"))
    if table is None:
        raise ValueError(
            f"Dimensión desconocida: {dimension!r}. Use: severidad, ocurrencia, deteccion."
        )
    if value not in table:
        raise ValueError("La valoración debe estar entre 1 y 10.")
    return table[value]
