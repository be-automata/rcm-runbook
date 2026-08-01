"""LLM retries must not duplicate entities (idempotent mutators)."""

from rcm_runbook.models.catalogs import FailurePattern
from rcm_runbook.models.domain import MaintenanceTask
from rcm_runbook.models.session import RCMSession


def _session() -> RCMSession:
    s = RCMSession()
    s.add_function(kind="primaria", verb="bombear", object="crudo",
                   performance_standard="850 GPM a 150 psi")
    s.add_functional_failure("F-001", "No alcanza el caudal requerido")
    return s


class TestIdempotentMutators:
    def test_duplicate_function_returns_existing(self):
        # La misma llamada, otra vez: el reintento del LLM no duplica.
        s = _session()
        original = s.functions["F-001"].performance_standard
        again = s.add_function(kind="primaria", verb="Bombear", object="CRUDO",
                               performance_standard=original)
        assert again.id == "F-001" and len(s.functions) == 1

    def test_un_estandar_distinto_no_se_descarta_en_silencio(self):
        # Este test decía antes «otro estándar da igual» y afirmaba que se
        # devolvía el existente: codificaba el defecto. `performance_standard`
        # es justo el campo que define la falla funcional, y en el guion de UAT
        # esto es el paso «que bombee bien» → «250 m³/h a 12 bar».
        import pytest

        from rcm_runbook.errors import ReglaDeNegocio

        s = _session()
        with pytest.raises(ReglaDeNegocio, match="reemplazar=True"):
            s.add_function(kind="primaria", verb="Bombear", object="CRUDO",
                           performance_standard="250 m³/h a 12 bar")
        assert len(s.functions) == 1, "no debe duplicar tampoco"

    def test_con_reemplazar_la_correccion_se_aplica(self):
        s = _session()
        fn = s.add_function(kind="primaria", verb="Bombear", object="CRUDO",
                            performance_standard="250 m³/h a 12 bar", reemplazar=True)
        assert fn.id == "F-001"
        assert s.functions["F-001"].performance_standard == "250 m³/h a 12 bar"
        assert len(s.functions) == 1

    def test_duplicate_ff_returns_existing(self):
        s = _session()
        again = s.add_functional_failure("F-001", "  no alcanza el caudal requerido ")
        assert again.id == "FF-001" and len(s.functional_failures) == 1

    def test_duplicate_failure_mode_returns_existing(self):
        s = _session()
        kwargs = dict(
            description="Cavitación por NPSH por debajo del requerido",
            mechanism="Cavitación", iso_code="LOO",
            cause="Operación fuera de las condiciones de diseño",
            root_cause="Filtro de succión obstruido",
            failure_pattern=FailurePattern.ALEATORIA,
        )
        first = s.add_failure_mode("FF-001", **kwargs)
        again = s.add_failure_mode("FF-001", **kwargs)
        assert again.id == first.id and len(s.failure_modes) == 1

    def test_distinct_mode_still_created(self):
        s = _session()
        base = dict(
            mechanism="Cavitación", iso_code="LOO",
            cause="Operación fuera de las condiciones de diseño",
            root_cause="Filtro obstruido", failure_pattern=FailurePattern.ALEATORIA,
        )
        s.add_failure_mode("FF-001", description="Cavitación por NPSH bajo", **base)
        s.add_failure_mode("FF-001", description="Desgaste del impulsor por erosión",
                           **{**base, "mechanism": "Erosión",
                              "cause": "Sólidos en el fluido",
                              "root_cause": "Filtración deficiente"})
        assert len(s.failure_modes) == 2

    def test_duplicate_task_ignored(self):
        s = _session()
        s.add_failure_mode("FF-001",
                           description="Cavitación por NPSH bajo",
                           mechanism="Cavitación", iso_code="LOO",
                           cause="Operación fuera de condiciones",
                           root_cause="Filtro obstruido",
                           failure_pattern=FailurePattern.ALEATORIA)
        task = MaintenanceTask(failure_mode_id="FM-001",
                               description="Análisis de vibraciones mensual en P-03070",
                               frequency="Mensual", duration_hours=2.0,
                               discipline="Predictivo")
        s.add_task(task)
        s.add_task(task.model_copy())
        assert len(s.tasks["FM-001"]) == 1
