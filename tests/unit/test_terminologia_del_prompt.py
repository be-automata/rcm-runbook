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

import pytest

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
        assert "No declares imposible" in INSTRUCTIONS_ES


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
        assert "ingeniero de confiabilidad" not in INSTRUCTIONS_ES
        assert "ingeniero de fiabilidad" in INSTRUCTIONS_ES
        # La palabra sigue apareciendo UNA vez, en la regla que la prohíbe. Eso
        # es correcto: la regla tiene que nombrar lo que corrige.
        assert INSTRUCTIONS_ES.count("confiabilidad") == 1
        assert "Fiabilidad (no confiabilidad)" in INSTRUCTIONS_ES


class TestElContratoDeTerminologia:
    """Las reglas de habla viven en el prompt, no en `consult_handbook`.

    `docs/GLOSARIO.md` es una tabla de correspondencia para quien programa; no
    contiene ninguna regla sobre cómo habla el agente y no debería estar en
    `_SOURCES`. Conectarla la volvería buscable, o sea dependiente de que el
    agente decida consultarla.
    """

    def test_el_eje_fallo_averia_esta_en_el_prompt(self):
        assert "**Fallo** es el evento" in INSTRUCTIONS_ES
        assert "**Avería** es el estado" in INSTRUCTIONS_ES

    def test_prohibe_averia_oculta(self):
        """En RCM lo oculto es el fallo (el evento), no la avería (el estado).
        Confundirlos es un error técnico, no de registro."""
        assert "«avería oculta»" in INSTRUCTIONS_ES
        assert "nunca digas" in INSTRUCTIONS_ES

    def test_manda_citar_verbatim_las_cadenas_congeladas(self):
        assert "verbatim y entre comillas" in INSTRUCTIONS_ES
        assert '"Falla Funcional"' in INSTRUCTIONS_ES, "el ejemplo tiene que ser literal"

    def test_las_cuatro_equivalencias_estan(self):
        for termino in ("en reserva", "búsqueda de fallos ocultos", "repuesto", "intervalo P-F"):
            assert termino in INSTRUCTIONS_ES, f"falta el equivalente de {termino!r}"
        assert "nunca «búsqueda de averías»" in INSTRUCTIONS_ES

    def test_el_glosario_sigue_sin_conectarse(self):
        """La tabla de correspondencia no va al contexto: no cabe y no gobierna
        el habla. Si alguien la añade a `_SOURCES`, este test lo dice."""
        from rcm_runbook.knowledge.handbook import _SOURCES

        assert "GLOSARIO.md" not in _SOURCES


class TestLaColisionDeFallo:
    """«fallo» pasó a ser el término del dominio, así que el error de software no
    puede seguir llamándose igual: la sección del prompt que enseña a
    distinguirlos quedaría ambigua justo donde exige precisión."""

    def test_el_prompt_llama_error_al_error_de_software(self):
        assert "**2. Error del sistema**" in INSTRUCTIONS_ES
        assert "**2. Fallo técnico**" not in INSTRUCTIONS_ES

    def test_y_lo_dice_explicitamente(self):
        assert "Nunca lo llames «fallo»" in INSTRUCTIONS_ES

    def test_el_mensaje_al_cliente_tambien(self):
        from rcm_runbook.app import _FALLO_GENERICO  # type: ignore[attr-defined]

        assert "fallo técnico" not in _FALLO_GENERICO
        assert "error" in _FALLO_GENERICO


class TestElRegistroNoSeEscapaALoQueVeElCliente:
    """El reemplazo de registro se hizo sobre ficheros `.py` y dejó fuera el HTML
    de la demo, que es literalmente lo primero que ve el cliente. Y un
    `str.replace` a ciegas rompió una concordancia: «a la ordenador».

    Este test mira las superficies visibles, no el código.
    """

    @pytest.mark.parametrize(
        "ruta",
        [
            "src/rcm_runbook/static/demo.html",
            "src/rcm_runbook/demo_page.py",
            "docs/COMPARTIR_DEMO_ES.md",
        ],
    )
    def test_sin_registro_latinoamericano(self, ruta):
        from pathlib import Path

        texto = Path(ruta).read_text("utf-8")
        for palabra in ("computadora", "monitoreo", "confiabilidad"):
            assert palabra not in texto, f"{ruta} dice «{palabra}» y lo ve el cliente"

    def test_la_concordancia_de_ordenador(self):
        """«ordenador» es masculino. Lo obvio para un hispanohablante y no para
        un `str.replace`."""
        from pathlib import Path

        for ruta in ("src/rcm_runbook/demo_page.py", "src/rcm_runbook/static/demo.html"):
            texto = Path(ruta).read_text("utf-8")
            assert "la ordenador" not in texto and "una ordenador" not in texto


class TestLaPantallaDeCredibilidad:
    """La regla dice CUÁNDO hay que descartar, no sólo qué no es un descarte.

    Antes el prompt sólo aclaraba que ReP no es un descarte. Nunca decía que todo
    modo propuesto deba evaluarse, así que el agente podía dejar fuera uno poco
    creíble sin registrarlo — y entonces el expediente no distingue «lo evaluamos y
    lo descartamos» de «no se nos ocurrió», que es justo lo que JA1011 pide poder
    distinguir.
    """

    def test_la_regla_obliga_a_evaluar_todo_modo_propuesto(self):
        assert "pantalla de credibilidad" in INSTRUCTIONS_ES
        assert "credible=False" in INSTRUCTIONS_ES, (
            "la regla debe nombrar el campo que hay que poner, no sólo el concepto"
        )

    def test_dice_por_que_y_no_solo_que(self):
        """Lo que el repo ya midió: dar el motivo en el punto de decisión bajó los
        rechazos inventados de 3/3 a 2/3 (comentario en tools.py). La regla lleva su
        porqué —el rastro en la hoja de auditoría— y no sólo la orden."""
        assert "hoja de auditoría" in INSTRUCTIONS_ES

    def test_la_afirmacion_del_prompt_es_cierta(self):
        """El prompt le dice al agente que el modo descartado queda en la hoja de
        auditoría. Si el entregable dejara de escribirlo, el prompt pasaría a
        afirmar algo falso y nadie se enteraría."""
        from rcm_runbook.export import excel

        fuente = inspect.getsource(excel._write_audit_sheet)
        assert "Modos descartados por no credibilidad" in fuente
        assert "non_credible_discard" in fuente, "y con su motivo, no sólo el id"

    def test_la_regla_no_se_come_la_seccion(self):
        """La regresión de la 0.3.0: el prompt creció un 43 % y diluyó la
        instrucción de la compuerta. Un bullet que ocupa el triple que sus vecinos
        es la misma enfermedad en pequeño."""
        seccion = INSTRUCTIONS_ES.split("## Reglas inquebrantables")[1].split("\n## ")[0]
        bullets = [b for b in seccion.split("\n- ") if b.strip()]
        largos = [len(b.strip().splitlines()) for b in bullets]
        credibilidad = next(
            len(b.strip().splitlines()) for b in bullets if "pantalla de credibilidad" in b
        )
        assert credibilidad <= max(largos), "no puede ser el bullet más largo por sí solo"
        assert credibilidad <= 4, f"ocupa {credibilidad} líneas; los vecinos rondan 2-3"

    def test_credibilidad_y_terminologia_son_reglas_distintas(self):
        """Una es procedimiento y la otra vocabulario. La 0.3.2 unificó dos reglas
        que ERAN la misma; fundir dos que no lo son es el error simétrico."""
        seccion = INSTRUCTIONS_ES.split("## Reglas inquebrantables")[1].split("\n## ")[0]
        bullets = [b for b in seccion.split("\n- ") if b.strip()]
        pantalla = [b for b in bullets if "pantalla de credibilidad" in b]
        rep = [b for b in bullets if "relubricación" in b]
        assert len(pantalla) == 1 and len(rep) == 1
        assert pantalla[0] is not rep[0], "van en bullets separados"


class TestElCodigoISOSeConsulta:
    """Henry: «los códigos se van creando nuevo, para que utilice uno existente
    hay que explicarle bien».

    Existían `lookup_iso14224` y `explain_iso_code` y ninguna se nombraba en el
    prompt, así que nada le decía al agente que consultara antes de asignar. El
    modelo adivinaba, el enum lo rechazaba, y el interesado veía el intento.
    Observado tres veces por caminos independientes: la llamada de UAT, las
    corridas del eval y el criterio [29] del verificador de producción.
    """

    def test_el_prompt_nombra_las_dos_herramientas(self):
        assert "lookup_iso14224" in INSTRUCTIONS_ES
        assert "explain_iso_code" in INSTRUCTIONS_ES

    def test_las_herramientas_que_nombra_existen(self):
        """Anti-pudrición: si alguien las renombra, el prompt manda al agente a
        llamar a algo que no está."""
        for nombre in ("lookup_iso14224", "explain_iso_code"):
            assert hasattr(tools_mod, nombre), nombre

    def test_los_codigos_de_ejemplo_estan_en_el_catalogo_del_cliente(self):
        """El prompt cita códigos concretos. Si el catálogo cambia y ellos no,
        el prompt enseña a usar valores que la herramienta rechazará."""
        from rcm_runbook.models.catalogs import fixture

        catalogo = {c.code for c in fixture().menu.iso14224_failure_mode_codes}
        for codigo in ("FTS", "BRD", "LOO", "VIB", "OTH", "UNK"):
            assert codigo in INSTRUCTIONS_ES, f"el prompt ya no cita {codigo}"
            assert codigo in catalogo, f"{codigo} salió del catálogo del cliente"

    def test_los_contraejemplos_siguen_siendo_invalidos(self):
        """`BA3113` y `ME4340` son de la tabla de EQUIPOS de la misma norma —los
        inventó el agente en las corridas del eval—. El prompt los usa como
        contraejemplo; si alguno entrara al catálogo, dejaría de serlo."""
        from rcm_runbook.models.catalogs import fixture

        catalogo = {c.code for c in fixture().menu.iso14224_failure_mode_codes}
        for codigo in ("BA3113", "ME4340"):
            assert codigo in INSTRUCTIONS_ES
            assert codigo not in catalogo, f"{codigo} ya no sirve de contraejemplo"

    def test_hay_salida_cuando_ninguno_encaja(self):
        """Sin `OTH`/`UNK` explícitos, «consulta el catálogo» se convierte en un
        callejón sin salida y el agente vuelve a inventar."""
        assert "OTH" in INSTRUCTIONS_ES and "UNK" in INSTRUCTIONS_ES


class TestNoSeHablaEnSintaxisDeHerramienta:
    """Henry: «a veces una instrucción de tal cosa igual a true».

    No es fuga de inglés —eso es otra regla— sino de implementación: el agente le
    enseña al interesado nombres de parámetro. La causa estaba en el propio
    prompt, que usa `draft=True` y `reemplazar=True` en su texto y nunca decía
    que eso no se le cuenta a una persona.
    """

    def test_la_regla_existe_y_prohibe_citarlos(self):
        assert "Nunca cites nombres ni valores de parámetro al interesado" in INSTRUCTIONS_ES

    def test_los_parametros_que_cita_la_regla_son_reales(self):
        """Anti-pudrición, y la razón es fina: la regla vale como ejemplo sólo si
        esos parámetros existen. Si `reemplazar` se renombrara, el prompt estaría
        prohibiendo decir algo que ya nadie dice, y dejaría fuera lo que sí."""
        reales = set()
        for nombre in dir(tools_mod):
            fn = getattr(getattr(tools_mod, nombre), "entrypoint", None)
            if fn is None or not callable(fn):
                continue
            try:
                reales.update(inspect.signature(fn).parameters)
            except (TypeError, ValueError):
                continue
        for parametro in ("draft", "reemplazar", "credible", "es_busqueda_de_fallas"):
            assert parametro in reales, f"la regla cita '{parametro}' y ya no existe"

    def test_ofrece_la_alternativa_en_castellano(self):
        """Prohibir sin dar el reemplazo deja al agente sin cómo decirlo, y una
        regla que no se puede cumplir se ignora entera."""
        # El prompt va envuelto a 88 columnas: se comparan espacios normalizados,
        # no la cadena literal, o el test se rompe al reajustar un párrafo.
        plano = " ".join(INSTRUCTIONS_ES.split())
        for frase in ("te preparo un borrador", "lo corrijo sobre el que ya estaba"):
            assert frase in plano, frase
