"""Controlled vocabularies — loaded from the frozen client-benchmark fixture.

The fixture (`rcm_runbook/data/benchmark_fixture.json`) is the single
published-language contract with the client's Excel dialect: catalogs here and
the export golden tests both consume it, so vocabulary and deliverable can
never drift independently.
"""

from __future__ import annotations

import json
from enum import StrEnum
from functools import lru_cache
from importlib import resources
from typing import Annotated

from pydantic import AfterValidator, BaseModel


class BenchmarkFixture(BaseModel):
    """Typed view of the frozen benchmark structure (ACL to the client's Excel dialect)."""

    class AmefSheet(BaseModel):
        header_row_excel: int
        title_rows: dict[str, list[str]]
        headers: list[str]
        od_npr_columns_present: bool

    class PlanSheet(BaseModel):
        header_row_excel: int
        title_rows: dict[str, list[str]]
        headers: list[str]

    class Menu(BaseModel):
        class IsoCode(BaseModel):
            code: str
            definition: str
            description: str

        class Policy(BaseModel):
            code: str
            label: str

        failure_patterns: list[str]
        policies: list[Policy]
        effect_locals: list[str]
        frequencies: list[str]
        iso14224_failure_mode_codes: list[IsoCode]
        disciplines: list[str]

    source_file: str
    sheets: list[str]
    amef: AmefSheet
    plan: PlanSheet
    menu: Menu
    sae_j1739_rows: list[list[str]]


@lru_cache(maxsize=1)
def fixture() -> BenchmarkFixture:
    raw = resources.files("rcm_runbook.data").joinpath("benchmark_fixture.json").read_text("utf-8")
    return BenchmarkFixture.model_validate(json.loads(raw))


# ---------------------------------------------------------------------------
# Maintenance policies (MENU-authoritative labels)
# ---------------------------------------------------------------------------


class MaintenancePolicy(StrEnum):
    MBC = "MBC"  # Mantenimiento basado en Condición (on-condition)
    MBT = "MBT"  # Mantenimiento basado en Tiempo (scheduled restoration)
    OHF = "OHF"  # Operar hasta la falla (run-to-failure)
    RD = "Rd"  # Rediseño (redesign / one-time change)
    BF = "BF"  # Búsqueda de Falla (failure finding)
    REP = "ReP"  # Relubricación programada (scheduled relubrication)
    EXED = "ExEd"  # Exploración de edad (age exploration)
    CC = "CC"  # Control de Calidad (quality control)


POLICY_LABELS_ES: dict[MaintenancePolicy, str] = {
    MaintenancePolicy.MBC: "Mantenimiento basado en Condición",
    MaintenancePolicy.MBT: "Mantenimiento basado en Tiempo",
    MaintenancePolicy.OHF: "Operar hasta la falla",
    MaintenancePolicy.RD: "Rediseño",
    MaintenancePolicy.BF: "Búsqueda de Falla",
    MaintenancePolicy.REP: "Relubricación programada",
    MaintenancePolicy.EXED: "Exploración de edad",
    MaintenancePolicy.CC: "Control de Calidad",
}

# PLAN DE MANTENIMIENTO one-hot strategy columns
POLICY_PLAN_COLUMN: dict[MaintenancePolicy, str] = {
    MaintenancePolicy.MBC: "Basado en Condición",
    MaintenancePolicy.MBT: "Preventivo",
    MaintenancePolicy.REP: "Preventivo",
    MaintenancePolicy.EXED: "Preventivo",
    MaintenancePolicy.BF: "Detección de Fallas",
    MaintenancePolicy.RD: "Otros tipos de Estrategias (Rediseño, etc).",
    MaintenancePolicy.CC: "Otros tipos de Estrategias (Rediseño, etc).",
    MaintenancePolicy.OHF: "Otros tipos de Estrategias (Rediseño, etc).",
}


class ConsequenceClass(StrEnum):
    OCULTA = "oculta"
    SEGURIDAD_AMBIENTE = "seguridad_ambiente"
    OPERACIONAL = "operacional"
    NO_OPERACIONAL = "no_operacional"


class FailurePattern(StrEnum):
    MORTALIDAD_INFANTIL = "Mortalidad Infantil"
    ALEATORIA = "Aleatoria"
    FIN_DE_VIDA_UTIL = "Fin de Vida Útil"
    ALEATORIA_FIN_DE_VIDA_UTIL = "Aleatoria/Fin de Vida Útil"


class DataSource(StrEnum):
    """Provenance of TPEF / failure-frequency estimates."""

    OREDA = "OREDA"
    HISTORIAL = "Historial CMMS"
    OPINION_EXPERTO = "Opinión de experto"
    FABRICANTE = "Fabricante"


def normalize_data_source(v: str) -> DataSource:
    """'OREDA (bombas API...)' → OREDA; 'Historial CMMS — 2 reemplazos...' → HISTORIAL.
    Acepta el valor canónico contenido al inicio del texto; rechaza lo ambiguo."""
    folded = _fold(v)
    matches = [
        ds for ds in DataSource
        if folded == _fold(ds.value) or folded.startswith(_fold(ds.value))
        or _fold(ds.value).split()[0] in folded.split("(")[0].split("—")[0].split()
    ]
    if len(set(matches)) == 1:
        return matches[0]
    valid = [ds.value for ds in DataSource]
    raise ValueError(f"Fuente de dato desconocida: {v!r}. Válidas: {valid}")


def normalize_failure_pattern(v: str) -> str:
    """'Fin de Vida Útil — degradación por...' → 'Fin de Vida Útil'. El patrón
    canónico debe aparecer al inicio; el combinado gana sobre sus componentes."""
    folded = _fold(str(v))
    candidates = sorted(
        (p for p in FailurePattern if folded.startswith(_fold(p.value))),
        key=lambda p: -len(p.value),
    )
    if candidates:
        return candidates[0].value
    valid = [p.value for p in FailurePattern]
    raise ValueError(f"Patrón de falla desconocido: {v!r}. Válidos: {valid}")


class EvidentRoute(StrEnum):
    """Decision-diagram route letters for evident failures (client dialect: ABCD)."""

    A = "A"
    B = "B"
    C = "C"
    D = "D"


class HiddenRoute(StrEnum):
    """Decision-diagram route letters for hidden failures (client dialect: AEFG)."""

    A = "A"
    E = "E"
    F = "F"
    G = "G"


# ---------------------------------------------------------------------------
# Fixture-backed vocabularies with typed, catalog-validated codes
# ---------------------------------------------------------------------------


def _valid_iso_code(v: str) -> str:
    codes = {c.code for c in fixture().menu.iso14224_failure_mode_codes}
    if v not in codes:
        raise ValueError(f"Código ISO 14224 desconocido: {v!r}. Válidos: {sorted(codes)}")
    return v


def _fold(s: str) -> str:
    import unicodedata

    nfd = unicodedata.normalize("NFD", s.strip().casefold())
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def _valid_frequency(v: str) -> str:
    """Normaliza mayúsculas/acentos contra el catálogo; rechaza lo desconocido."""
    folded = _fold(v)
    for canonical in fixture().menu.frequencies:
        if _fold(canonical) == folded:
            return canonical
    raise ValueError(
        f"Frecuencia desconocida: {v!r}. Válidas: {fixture().menu.frequencies}"
    )


def _valid_discipline(v: str) -> str:
    """Normaliza contra el catálogo: match exacto (casefold) o el input contiene
    exactamente una disciplina canónica ('Técnico Predictivo' → 'Predictivo',
    'Instrumentación' → 'Instrumentista' vía prefijo)."""
    folded = _fold(v)
    disciplines = fixture().menu.disciplines
    for canonical in disciplines:
        if _fold(canonical) == folded:
            return canonical
    contained = [
        c for c in disciplines
        if _fold(c) in folded or folded.startswith(_fold(c)[:8])
    ]
    if len(contained) == 1:
        return contained[0]
    raise ValueError(
        f"Disciplina desconocida: {v!r}. Válidas: {disciplines}"
    )


# Distinct types so mode-code / frequency / discipline can't cross-assign silently.
FailureModeCode = Annotated[str, AfterValidator(_valid_iso_code)]
Frequency = Annotated[str, AfterValidator(_valid_frequency)]
Discipline = Annotated[str, AfterValidator(_valid_discipline)]

# ISO 14224 mechanism (Table B.2-style) and cause (Table B.3-style) controlled vocabularies.
# The benchmark MENU does not enumerate these; these lists follow ISO 14224 Annex B and the
# vocabulary observed in the client's own AMEF rows.
MECHANISMS_ES: list[str] = [
    "Falla Mecánica",
    "Fuga",
    "Cavitación",
    "Corrosión",
    "Desgaste",
    "Erosión",
    "Fatiga",
    "Recalentamiento",
    "Falla Eléctrica",
    "Falla de Instrumentación",
    "Falla de Material",
    "Bloqueo/Obstrucción",
    "Otro",
]

CAUSE_CATEGORIES_ES: list[str] = [
    "Error de Diseño",
    "Error de Fabricación/Instalación",
    "Error de Operación",
    "Error de Mantenimiento",
    "Falla por desgaste",
    "Operación fuera de las condiciones de diseño",
    "Causa externa/ambiental",
    "Envejecimiento",
    "Otro",
]


def iso_code_info(code: str) -> tuple[str, str]:
    """Return (definition, description) for a MENU ISO 14224 failure-mode code."""
    for c in fixture().menu.iso14224_failure_mode_codes:
        if c.code == code:
            return c.definition, c.description
    raise KeyError(code)


# ---------------------------------------------------------------------------
# SAE J1739 S/O/D anchor tables (Spanish, from benchmark "SAE-J1739" sheet)
# ---------------------------------------------------------------------------

SAE_SEVERITY_ES: dict[int, str] = {
    10: "Peligroso sin previo aviso — riesgo muy alto, afecta seguridad/normativa sin advertencia",
    9: "Peligroso con advertencia — riesgo muy alto, afecta seguridad/normativa con advertencia",
    8: "Muy alta — el equipo no funciona, pérdida de función primaria",
    7: "Alta — rendimiento menor del 55%, operación degradada severa",
    6: "Moderado — rendimiento menor del 60%, operación degradada",
    5: "Moderada baja — rendimiento menor del 75%, operación con incomodidad",
    4: "Muy baja — notado por la mayoría de los operadores",
    3: "Menor — notado solo por algunos operadores",
    2: "Muy menor — notado solo por operadores atentos",
    1: "Ninguno — no afecta la operación del equipo",
}

SAE_OCCURRENCE_ES: dict[int, str] = {
    10: "Muy alta: la falla es casi inevitable (≥ 1 en 2)",
    9: "Muy alta (1 en 3)",
    8: "Alta: fallas repetidas (1 en 8)",
    7: "Alta (1 en 20)",
    6: "Moderada: fallas ocasionales (1 en 80)",
    5: "Moderada (1 en 400)",
    4: "Moderada baja (1 en 2.000)",
    3: "Baja: relativamente pocas fallas (1 en 15.000)",
    2: "Muy baja (1 en 150.000)",
    1: "Remota: la falla es improbable (≤ 1 en 1.500.000)",
}

SAE_DETECTION_ES: dict[int, str] = {
    10: "Incertidumbre absoluta — no hay control que detecte el modo de falla",
    9: "Muy remota — control muy difícilmente detecta",
    8: "Remota — control difícilmente detecta",
    7: "Muy baja — capacidad muy baja de detección",
    6: "Baja — capacidad baja de detección",
    5: "Moderada — capacidad moderada de detección",
    4: "Moderadamente alta — capacidad moderadamente alta",
    3: "Alta — capacidad alta de detección",
    2: "Muy alta — capacidad muy alta de detección",
    1: "Casi segura — el control detecta casi con certeza (monitoreo online confiable)",
}
