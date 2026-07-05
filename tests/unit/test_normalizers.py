"""Catalog input normalization: unambiguous near-misses accepted, unknowns rejected."""

import pytest
from pydantic import ValidationError

from rcm_runbook.models.catalogs import (
    DataSource,
    normalize_data_source,
)
from rcm_runbook.models.domain import FailureMode, MaintenanceTask


def _fm(**overrides):
    base = dict(
        id="FM-001", functional_failure_id="FF-001",
        description="Cavitación por NPSH por debajo del requerido",
        mechanism="Cavitación", iso_code="LOO",
        cause="Operación fuera de las condiciones de diseño",
        root_cause="Filtro obstruido", failure_pattern="Aleatoria",
    )
    base.update(overrides)
    return FailureMode(**base)


class TestFailurePattern:
    def test_verbose_suffix_normalized(self):
        fm = _fm(failure_pattern="Fin de Vida Útil — degradación del sello por contaminación")
        assert fm.failure_pattern == "Fin de Vida Útil"

    def test_combined_pattern_wins_over_component(self):
        fm = _fm(failure_pattern="Aleatoria/Fin de Vida Útil (según historial)")
        assert fm.failure_pattern == "Aleatoria/Fin de Vida Útil"

    def test_unknown_pattern_rejected(self):
        with pytest.raises(ValidationError, match="Patrón de falla desconocido"):
            _fm(failure_pattern="Degradación progresiva hasta fallo súbito")


class TestDataSource:
    def test_parenthetical_oreda(self):
        assert normalize_data_source(
            "OREDA (bombas centrífugas API en servicio similar)"
        ) == DataSource.OREDA

    def test_historial_with_detail(self):
        assert normalize_data_source(
            "Historial CMMS — 2 reemplazos de impulsor en 8 años"
        ) == DataSource.HISTORIAL

    def test_unknown_rejected(self):
        with pytest.raises(ValueError, match="Fuente de dato desconocida"):
            normalize_data_source("me lo dijo un compadre")


class TestFrequencyDiscipline:
    def test_frequency_case_and_accent_insensitive(self):
        t = MaintenanceTask(failure_mode_id="FM-001",
                            description="Prueba funcional del lazo de disparo",
                            frequency="tri-anual", duration_hours=2, discipline="Mecánico")
        assert t.frequency == "Tri-Anual"

    def test_discipline_synonym_contained(self):
        t = MaintenanceTask(failure_mode_id="FM-001",
                            description="Análisis de vibraciones mensual",
                            frequency="Mensual", duration_hours=2,
                            discipline="Técnico Predictivo")
        assert t.discipline == "Predictivo"

    def test_discipline_prefix_instrumentacion(self):
        t = MaintenanceTask(failure_mode_id="FM-001",
                            description="Calibración del transmisor de succión",
                            frequency="Anual", duration_hours=2,
                            discipline="Instrumentación")
        assert t.discipline == "Instrumentista"

    def test_free_text_frequency_rejected(self):
        with pytest.raises(ValidationError, match="Frecuencia desconocida"):
            MaintenanceTask(failure_mode_id="FM-001",
                            description="Overhaul mayor de la bomba",
                            frequency="Cada 4 años", duration_hours=8,
                            discipline="Mecánico")
