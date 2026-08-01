"""RCM domain entities and value objects (SAE J1739 FMEA + JA1011 decision logic).

Rules encoded here (from domain review):
- Functions carry a quantitative performance standard and a kind
  (primaria/secundaria/protección).
- Effects are described assuming NO maintenance intervention (JA1011 Q4).
- Cause is distinct from failure mode (separate vocabularies + semantic check).
- Non-credible failure modes carry a documented discard (kept, never deleted).
- TPEFEstimate is owned solely by FailureMode; plan rows project from it.
- RiskScore/DecisionResult store an input-snapshot hash for staleness detection.
- DecisionResult.justification is mandatory (JA1011 auditability).
"""

from __future__ import annotations

import hashlib
import unicodedata
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field, field_validator, model_validator

from rcm_runbook.models.catalogs import (
    ConsequenceClass,
    DataSource,
    Discipline,
    EvidentRoute,
    FailureModeCode,
    FailurePattern,
    Frequency,
    HiddenRoute,
    MaintenancePolicy,
    normalize_failure_pattern,
)


class FunctionKind(StrEnum):
    PRIMARIA = "primaria"
    SECUNDARIA = "secundaria"
    PROTECCION = "proteccion"


class Function(BaseModel):
    id: str  # F-001
    kind: FunctionKind
    verb: str = Field(min_length=2, description="Verbo de la función (bombear, contener...)")
    object: str = Field(min_length=2, description="Objeto (agua de proceso, presión...)")
    performance_standard: str = Field(
        min_length=3,
        description="Estándar cuantitativo/verificable (p.ej. '120 m³/h a 6 bar')",
    )

    @field_validator("performance_standard")
    @classmethod
    def standard_must_be_concrete(cls, v: str) -> str:
        vague = {"adecuado", "adecuada", "bien", "correctamente", "normal", "bueno", "buena"}
        if v.strip().lower() in vague:
            raise ValueError(
                "El estándar de desempeño debe ser cuantitativo o verificable "
                f"('{v}' es vago). Ej.: '120 m³/h a 6 bar', 'sin fugas visibles'."
            )
        return v

    @property
    def statement(self) -> str:
        return f"{self.verb} {self.object} — {self.performance_standard}"


class FunctionalFailure(BaseModel):
    id: str  # FF-001
    function_id: str
    description: str = Field(min_length=5, description="Forma en que se pierde la función")


class TPEFEstimate(BaseModel):
    """Tiempo Promedio Entre Fallas — single source of truth lives on FailureMode."""

    value_hours: float = Field(gt=0)
    fuente: DataSource
    note: str = ""

    @property
    def value_years(self) -> float:
        return self.value_hours / 8760.0


class FailureMode(BaseModel):
    id: str  # FM-001
    functional_failure_id: str
    description: str = Field(min_length=5, description="Modo de falla accionable y específico")
    mechanism: str = Field(min_length=3, description="Mecanismo de Falla (ISO 14224 B.2)")
    iso_code: FailureModeCode  # Código ISO 14224 (modo de falla, MENU-authoritative)
    cause: str = Field(min_length=3, description="Causa de la Falla (ISO 14224 B.3)")
    root_cause: str = Field(min_length=3, description="Causa Raíz")
    failure_pattern: Annotated[FailurePattern, BeforeValidator(normalize_failure_pattern)]
    credible: bool = True
    non_credible_discard: str = Field(
        default="",
        description="Justificación documentada del descarte por no credibilidad "
        "(se conserva en el registro de auditoría, nunca se elimina)",
    )
    tpef: TPEFEstimate | None = None
    pf_interval_hours: float | None = Field(default=None, gt=0)
    weibull_beta: float | None = Field(default=None, gt=0)
    weibull_eta_hours: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def discard_requires_reason(self) -> FailureMode:
        if not self.credible and len(self.non_credible_discard.strip()) < 10:
            raise ValueError(
                "Un modo de falla no creíble requiere justificación documentada "
                "(descarte por no credibilidad, mínimo 10 caracteres)."
            )
        return self

    @model_validator(mode="after")
    def cause_must_differ_from_mode(self) -> FailureMode:
        # Sin quitar acentos, el modo LITERAL escrito sin tildes pasaba como
        # causa válida: «falla de rodamientos con vibracion creciente». El repo
        # ya tenía el comparador correcto en RCMSession._same_text y este
        # validador no lo usaba, así que add_failure_mode consideraba
        # «vibracion» y «vibración» el mismo modo mientras este los veía
        # distintos.
        cause = _sin_acentos(self.cause).strip().lower()
        mode = _sin_acentos(self.description).strip().lower()
        if cause == mode or (len(cause) > 12 and (cause in mode or mode in cause)):
            raise ValueError(
                "La causa no puede ser una reformulación del modo de falla. "
                "Modo = cómo se manifiesta técnicamente; causa = por qué se produce."
            )
        return self


def _sin_acentos(t: str) -> str:
    plano = unicodedata.normalize("NFKD", t)
    return "".join(c for c in plano if not unicodedata.combining(c))


MAINTENANCE_ASSUMPTION_MARKERS = (
    "mantenimiento previene",
    "se detecta en el pm",
    "el preventivo lo",
    "lo detecta el monitoreo",
    "no pasa nada porque",
    "se corrige en la inspección",
    "la inspección lo detecta",
)


class Effect(BaseModel):
    """Efectos asumiendo que NO se realiza ninguna tarea de mantenimiento (JA1011 Q4)."""

    failure_mode_id: str
    local: str = Field(min_length=5, description="Efecto local (equipo)")
    system: str = Field(min_length=5, description="Efecto en el sistema/proceso")
    plant: str = Field(min_length=3, description="Efecto en planta/negocio")
    is_hidden: bool
    evident_route: EvidentRoute | None = None
    hidden_route: HiddenRoute | None = None
    safety: bool = False
    environment: bool = False
    operational: bool = False
    non_operational: bool = False

    @model_validator(mode="after")
    def route_matches_visibility(self) -> Effect:
        if self.is_hidden and self.evident_route is not None:
            raise ValueError("Una falla oculta no puede tener ruta evidente (ABCD).")
        if not self.is_hidden and self.hidden_route is not None:
            raise ValueError("Una falla evidente no puede tener ruta oculta (AEFG).")
        return self

    @model_validator(mode="after")
    def no_maintenance_assumption(self) -> Effect:
        text = f"{self.local} {self.system} {self.plant}".lower()
        for marker in MAINTENANCE_ASSUMPTION_MARKERS:
            if marker in text:
                raise ValueError(
                    "El efecto debe describirse asumiendo que NO se hace mantenimiento "
                    f"(se detectó supuesto de mantenimiento: '{marker}'). "
                    "Describa qué pasa si nadie interviene."
                )
        return self

    @model_validator(mode="after")
    def at_least_one_consequence_flag(self) -> Effect:
        if not (self.safety or self.environment or self.operational or self.non_operational):
            raise ValueError(
                "Marque al menos una consecuencia: Seguridad, Ambiente, "
                "Operacional o No Operacional."
            )
        return self


class Control(BaseModel):
    failure_mode_id: str
    kind: Literal["preventivo", "detectivo", "mitigante"]
    description: str = Field(min_length=5)


class RiskScore(BaseModel):
    """SAE J1739 S/O/D. `input_hash` detects staleness when upstream entries change."""

    failure_mode_id: str
    severity: int = Field(ge=1, le=10)
    occurrence: int = Field(ge=1, le=10)
    detection: int = Field(ge=1, le=10)
    is_residual: bool = False
    input_hash: str = ""

    @property
    def rpn(self) -> int:
        return self.severity * self.occurrence * self.detection

    @property
    def so(self) -> int:
        return self.severity * self.occurrence

    @property
    def sod(self) -> str:
        return f"S{self.severity}-O{self.occurrence}-D{self.detection}"


class DecisionResult(BaseModel):
    failure_mode_id: str
    consequence_class: ConsequenceClass
    policy: MaintenancePolicy
    justification: str = Field(
        min_length=15,
        description="Justificación técnica de la política (requisito de auditoría JA1011)",
    )
    evident_route: EvidentRoute | None = None
    hidden_route: HiddenRoute | None = None
    provisional: bool = False  # ExEd/CC mapping pending client confirmation
    hitl_confirmed_by: str | None = None
    ffi_hours: float | None = None
    recommended_interval: str = ""
    input_hash: str = ""


class RecommendedAction(BaseModel):
    failure_mode_id: str
    what: str = Field(min_length=10)
    who: str = Field(min_length=2)
    when: str = Field(min_length=2)
    resources: str = ""
    verification: str = Field(min_length=5, description="Cómo se verificará su eficacia")


class MaintenanceTask(BaseModel):
    """Plan row. TPEF is NOT stored here — it projects from the owning FailureMode."""

    failure_mode_id: str
    description: str = Field(min_length=10)
    frequency: Frequency
    duration_hours: float = Field(gt=0)
    discipline: Discipline
    requires_shutdown: bool = False


def snapshot_hash(*parts: object) -> str:
    """Stable digest of decision/score inputs for staleness detection."""
    joined = "\x1f".join(str(p) for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def failure_mode_snapshot(
    fm: FailureMode,
    effect: Effect | None,
    controls: list[Control] | None = None,
) -> str:
    """Digest of every decision-affecting input: the mode itself (incl. Weibull
    parameters and credibility), its effect, and the current controls (they justify
    the Detection rating)."""
    return snapshot_hash(
        fm.description,
        fm.mechanism,
        fm.iso_code,
        fm.cause,
        fm.root_cause,
        fm.failure_pattern,
        fm.credible,
        fm.tpef.model_dump_json() if fm.tpef else "",
        fm.pf_interval_hours,
        fm.weibull_beta,
        fm.weibull_eta_hours,
        effect.model_dump_json() if effect else "",
        "|".join(f"{c.kind}:{c.description}" for c in (controls or [])),
    )
