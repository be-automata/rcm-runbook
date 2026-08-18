"""Reglas de habla del agente que viven en el prompt, no en una herramienta.

Spec: `specs/glosario-y-terminologia.md` (parcial: las tres reglas que no
dependen de resolver el eje fallo/avería).

Están acá y no en `consult_handbook` por lo que documenta `factory.py`: el estado
de sesión se inyectaba sólo si el agente decidía llamar a `get_progress`, y el
resultado medido fue «31 turnos, 0 modos de falla registrados». Una regla que
gobierna cada frase no puede depender de que el agente decida buscarla.
"""

from __future__ import annotations

import inspect

from rcm_runbook.agent import tools as tools_mod
from rcm_runbook.agent.instructions_es import INSTRUCTIONS_ES


def _herramientas_que_aceptan_reemplazar() -> set[str]:
    """Las que de verdad lo aceptan, leídas de sus firmas."""
    encontradas = set()
    for nombre in dir(tools_mod):
        obj = getattr(tools_mod, nombre)
        fn = getattr(obj, "entrypoint", None)
        if fn is None or not callable(fn):
            continue
        try:
            if "reemplazar" in inspect.signature(fn).parameters:
                encontradas.add(nombre)
        except (TypeError, ValueError):
            continue
    return encontradas


class TestLaListaDeCapacidadesNoSePudre:
    """El agente declaró imposible una corrección que sí podía hacer, y le
    trasladó al interesado un límite inventado. La enumeración del prompt lo
    arregla, pero una lista escrita a mano es un contrato sin guardián: en cuanto
    alguien añada o quite un `reemplazar=`, el prompt miente."""

    def test_el_prompt_nombra_exactamente_las_que_lo_aceptan(self):
        reales = _herramientas_que_aceptan_reemplazar()
        assert reales, "ninguna herramienta acepta `reemplazar`: la firma cambió"
        nombradas = {n for n in reales if n in INSTRUCTIONS_ES}
        assert nombradas == reales, (
            f"el prompt no nombra {sorted(reales - nombradas)}, que sí aceptan "
            "`reemplazar=True`: el agente no sabrá que puede corregirlas"
        )

    def test_y_no_nombra_ninguna_que_no_lo_acepte(self):
        """La dirección contraria: prometer una capacidad inexistente hace que el
        agente intente algo que la herramienta va a rechazar."""
        reales = _herramientas_que_aceptan_reemplazar()
        seccion = INSTRUCTIONS_ES.split("## Corregir un dato ya registrado")[1]
        seccion = seccion.split("##")[0]
        for nombre in ("record_effect", "record_control", "record_functional_failure"):
            assert nombre not in seccion, (
                f"el prompt promete corregir {nombre}, que no acepta `reemplazar`"
            )
        assert all(n in seccion for n in reales)

    def test_prohibe_declarar_limites_no_observados(self):
        assert "Nunca declares imposible algo que no hayas intentado" in INSTRUCTIONS_ES


class TestLaGlosaDeFrecuencias:
    """`Bi-Anual` vale dos años y la RAE define bianual como dos veces al año.
    Factor 4 en la dirección insegura sobre un dispositivo de protección. La
    etiqueta no se puede cambiar —es el MENU del cliente— así que la defensa es
    que el agente diga siempre el número de horas."""

    def test_la_regla_viaja_en_el_prompt(self):
        assert "glosan SIEMPRE en horas" in INSTRUCTIONS_ES

    def test_nombra_el_caso_que_motiva_la_regla_con_su_numero(self):
        assert "Bi-Anual" in INSTRUCTIONS_ES
        assert "17.520" in INSTRUCTIONS_ES, "sin el número, la regla es un consejo"

    def test_las_horas_que_afirma_el_prompt_son_las_del_catalogo(self):
        """Que el prompt y el catálogo no puedan divergir en silencio."""
        from rcm_runbook.models.catalogs import FRECUENCIA_EN_HORAS

        assert FRECUENCIA_EN_HORAS["Bi-Anual"] == 17520


class TestRegistroDeEspana:
    def test_el_prompt_no_se_contradice_sobre_fiabilidad(self):
        """Decía «ingeniero de confiabilidad» y dos líneas después «Mantenimiento
        Centrado en la Fiabilidad». El mercado es España: fiabilidad."""
        assert "confiabilidad" not in INSTRUCTIONS_ES
        assert "Fiabilidad" in INSTRUCTIONS_ES
